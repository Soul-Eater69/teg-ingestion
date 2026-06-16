"""IDP LLM gateway client (async, structured output).

The gateway is OpenAI-compatible with two POC-confirmed quirks: custom IDP bearer
auth (see idp_auth) and a response that wraps the single result under "choice"
instead of "choices". Guardrails are gateway-side, so there is no prompt
sanitization here. The output structure is requested as a json_schema built from the
caller's pydantic model and re-validated locally.
"""

from __future__ import annotations

import json
from typing import TypeVar

import httpx
from pydantic import BaseModel

from teg.config.settings import Settings
from teg.integrations.http_retry import post_with_retry
from teg.integrations.llm.idp_auth import IDPCustomAuth

ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class IdpLLMClient:
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        model: str,
        completion_path: str = "/api/v1/chatcompletions",
        api_version: str = "2024-04-01-preview",
        reasoning_effort: str | None = None,
        max_output_tokens: int | None = None,
        max_retries: int = 5,
        retry_base_delay: float = 1.0,
        retry_max_delay: float = 30.0,
    ) -> None:
        self._http = http_client
        self._model = model
        self._completion_path = completion_path
        self._api_version = api_version
        self._reasoning_effort = reasoning_effort or None
        self._max_output_tokens = max_output_tokens
        self._max_retries = max_retries  # retry 429/5xx/transient-network with backoff
        self._retry_base_delay = retry_base_delay
        self._retry_max_delay = retry_max_delay
        # Running token usage across all calls (from the gateway's 'usage'); read via .usage for
        # eval cost reporting. Not part of the contract - tests/production ignore it.
        self._calls = 0
        self._prompt_tokens = 0
        self._completion_tokens = 0

    async def aclose(self) -> None:
        """Close the underlying httpx client (call when done; e.g. scripts)."""
        await self._http.aclose()

    @property
    def usage(self) -> dict:
        """Accumulated token usage: calls, prompt/completion/total tokens, and per-call averages."""
        total = self._prompt_tokens + self._completion_tokens
        n = self._calls or 1
        return {
            "calls": self._calls,
            "prompt_tokens": self._prompt_tokens,
            "completion_tokens": self._completion_tokens,
            "total_tokens": total,
            "avg_prompt": round(self._prompt_tokens / n, 1),
            "avg_completion": round(self._completion_tokens / n, 1),
            "avg_total": round(total / n, 1),
        }

    async def complete(self, *, system: str, user: str, schema: type[ModelT]) -> ModelT:
        body: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": _strict_schema(schema),
                    "strict": True,
                },
            },
            "api_version": self._api_version,
        }
        if self._reasoning_effort:
            body["reasoning_effort"] = self._reasoning_effort
        if self._max_output_tokens:
            body["max_completion_tokens"] = self._max_output_tokens

        response = await post_with_retry(
            self._http, self._completion_path, body,
            max_retries=self._max_retries, base_delay=self._retry_base_delay,
            max_delay=self._retry_max_delay,
        )
        payload = response.json()
        usage = payload.get("usage") or {}
        self._calls += 1
        self._prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self._completion_tokens += int(usage.get("completion_tokens") or 0)
        content = _extract_content(payload)
        return _validate(content, schema)


def _strict_schema(schema: type[BaseModel]) -> dict:
    """Pydantic JSON schema, transformed to satisfy OpenAI structured-output strict mode.

    Strict mode constrains generation so the reply provably matches the schema, but it requires
    every object to set additionalProperties=false, list every property in `required`, and carry
    no `default` keys - none of which pydantic emits for fields with defaults. Apply those
    recursively (including $defs and array items). Defaulted fields become always-emitted; the
    model fills the empty value (""/[]) where it used to omit them.
    """
    return _strictify(schema.model_json_schema(by_alias=True))


def _strictify(node):
    if isinstance(node, dict):
        node.pop("default", None)  # strict mode rejects default keys
        if isinstance(node.get("properties"), dict):
            node["required"] = list(node["properties"].keys())
            node["additionalProperties"] = False
        for value in node.values():
            _strictify(value)
    elif isinstance(node, list):
        for item in node:
            _strictify(item)
    return node


def _validate(content: str, schema: type[ModelT]) -> ModelT:
    """Validate the model output, tolerating a single-key wrapper.

    response_format json_schema is not strict, so a model occasionally wraps the payload under
    one key (e.g. {"description": {"text": ...}} instead of {"text": ...}). Try the content as
    given; on failure, if it is a single-key object, unwrap one level and retry before erroring.
    """
    try:
        return schema.model_validate_json(content)
    except Exception as exc:  # noqa: BLE001
        try:
            data = json.loads(content)
        except Exception:
            data = None
        if isinstance(data, dict) and len(data) == 1:
            inner = next(iter(data.values()))
            try:
                return schema.model_validate(inner)
            except Exception:
                pass
        raise LLMError(f"LLM output failed {schema.__name__} validation: {exc}") from exc


def _extract_content(payload: dict) -> str:
    if payload.get("error"):
        raise LLMError(str(payload["error"]))
    choice = payload.get("choice")  # IDP gateway quirk: single "choice"
    if choice is None:
        choices = payload.get("choices") or []
        choice = choices[0] if choices else {}
    content = (choice.get("message") or {}).get("content")
    if not content:
        raise LLMError("LLM returned no content")
    return content


def build_llm_client(
    settings: Settings,
    *,
    model: str | None = None,
    max_retries: int | None = None,
    retry_max_delay: float | None = None,
) -> IdpLLMClient:
    """Build the gateway client. ``model`` overrides settings.llm_model (e.g. a stronger judge
    model for eval). ``max_retries`` / ``retry_max_delay`` override the retry budget - a rate-limited
    judge (gpt-5) needs more patient retries to ride out its 429 window."""
    auth = IDPCustomAuth(
        app_id=settings.llm_app_id,
        auth_url=settings.idp_auth_url,
        client_id=settings.idp_client_id,
        client_secret=settings.idp_client_secret,
        user=settings.idp_user,
        password=settings.idp_password,
        verify_ssl=settings.llm_verify_ssl,
    )
    http_client = httpx.AsyncClient(
        base_url=settings.llm_base_url,
        auth=auth,
        timeout=settings.llm_timeout_seconds,
        verify=settings.llm_verify_ssl,
    )
    return IdpLLMClient(
        http_client,
        model=model or settings.llm_model,
        completion_path=settings.llm_completion_path,
        api_version=settings.llm_api_version,
        reasoning_effort=settings.llm_reasoning_effort or None,
        max_output_tokens=settings.llm_max_output_tokens,
        max_retries=settings.llm_max_retries if max_retries is None else max_retries,
        retry_max_delay=30.0 if retry_max_delay is None else retry_max_delay,
    )
