"""IDP bearer auth for the LLM gateway.

Fetches a JWT from the IDP token endpoint, caches it, injects it as
``Authorization: Bearer`` plus the ``app-id`` header, and refreshes once on a 401.
Async-only: the gateway client is an httpx.AsyncClient.

A freshly-minted token can be transiently rejected by the gateway (activation /
propagation delay) - so we retry once on ANY 401, including the very first request of a
run. A lock coalesces concurrent first-fetches so high concurrency doesn't stampede the
token endpoint (and only one coroutine refreshes per rejected token).
"""

from __future__ import annotations

import asyncio
import sys

import httpx

# The token POST itself is flaky on the dev STS: the FIRST fetch of a run is sometimes
# rejected (401 server_error / SecretInitialisationException) or hits a 5xx/timeout, even
# though a standalone call succeeds. Retry the fetch with exponential backoff before giving
# up; a genuinely-bad credential just fails all attempts after a few seconds.
_TOKEN_MAX_RETRIES = 3
_TOKEN_BACKOFF_SECONDS = 0.5
_TOKEN_RETRY_STATUS = {401, 408, 429}  # plus any 5xx; transient on this STS


class IDPCustomAuth(httpx.Auth):
    def __init__(
        self,
        *,
        app_id: str,
        auth_url: str,
        client_id: str,
        client_secret: str,
        user: str,
        password: str,
        verify_ssl: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._app_id = app_id
        self._auth_url = auth_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._user = user
        self._password = password
        self._transport = transport  # test seam (inject a MockTransport); None = real network
        self._verify_ssl = verify_ssl
        self._token: str | None = None
        self._lock = asyncio.Lock()

    async def async_auth_flow(self, request: httpx.Request):
        token = await self._ensure_token(stale=None)
        self._apply(request, token)

        response = yield request
        # Any 401 -> the token was rejected (expired, OR a freshly-minted token not yet active
        # on the gateway - the first request of a run hits this). Refresh once and retry. A
        # second 401 then surfaces to the caller (genuinely bad creds / permissions).
        if response.status_code == 401:
            token = await self._ensure_token(stale=token)
            self._apply(request, token)
            yield request

    async def _ensure_token(self, *, stale: str | None) -> str:
        """Return a usable token, fetching one under the lock if missing or matching ``stale``.

        Passing the token that just 401'd as ``stale`` means only the first coroutine to see
        that rejection re-fetches; the rest reuse the new token instead of stampeding.
        """
        async with self._lock:
            if self._token is None or self._token == stale:
                self._token = await self._fetch_token()
            return self._token

    def _apply(self, request: httpx.Request, token: str) -> None:
        request.headers["Authorization"] = f"Bearer {token}"
        request.headers["app-id"] = str(self._app_id)

    async def _fetch_token(self) -> str:
        headers = {
            "Accept": "*/*",
            "ClientId": self._client_id,
            "ClientSecret": self._client_secret,
            "scope": "profile openid roles permissions",
        }
        body = {"username": self._user, "password": self._password}
        last_error: Exception | None = None
        print(f"[auth] fetching IDP token from {self._auth_url}", file=sys.stderr, flush=True)
        async with httpx.AsyncClient(verify=self._verify_ssl, transport=self._transport) as client:
            for attempt in range(_TOKEN_MAX_RETRIES + 1):
                if attempt:
                    await asyncio.sleep(_TOKEN_BACKOFF_SECONDS * (2 ** (attempt - 1)))
                try:
                    response = await client.post(self._auth_url, headers=headers, json=body)
                except httpx.TransportError as exc:  # connect/read timeout, conn reset, ...
                    last_error = exc
                    print(f"[auth] attempt {attempt + 1}/{_TOKEN_MAX_RETRIES + 1}: cannot reach token "
                          f"endpoint ({type(exc).__name__}: {exc})", file=sys.stderr, flush=True)
                    continue
                if response.status_code in _TOKEN_RETRY_STATUS or response.status_code >= 500:
                    last_error = httpx.HTTPStatusError(
                        f"token endpoint {response.status_code}", request=response.request,
                        response=response)
                    body_text = " ".join(response.text.split())[:300]
                    print(f"[auth] attempt {attempt + 1}/{_TOKEN_MAX_RETRIES + 1}: HTTP "
                          f"{response.status_code} from token endpoint :: {body_text}",
                          file=sys.stderr, flush=True)
                    continue  # transient on this STS - back off and retry
                response.raise_for_status()  # any other 4xx is a real error - surface it
                token = response.json().get("jwt_token")
                if not token:
                    raise RuntimeError("IDP token response missing jwt_token")
                print("[auth] IDP token acquired", file=sys.stderr, flush=True)
                return str(token)
        print(f"[auth] token fetch FAILED after {_TOKEN_MAX_RETRIES + 1} attempt(s): {last_error}",
              file=sys.stderr, flush=True)
        raise last_error or RuntimeError("IDP token fetch failed")
