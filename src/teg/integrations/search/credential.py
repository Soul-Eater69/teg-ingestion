"""Azure AI Search credential: service principal (preferred) or admin API key.

Mirrors the vs repo - ClientSecretCredential(tenant_id, client_id, client_secret) when
the Azure AD service-principal config is present, else the static admin key. Returns an
async-capable credential for the aio search clients (build_search_credential) and the
bearer token for the REST index-management call (search_bearer_token).
"""

from __future__ import annotations

from teg.config.settings import Settings

_SEARCH_SCOPE = "https://search.azure.com/.default"

try:  # azure SDK is the optional 'search' extra
    from azure.core.credentials import AzureKeyCredential
    from azure.identity import ClientSecretCredential as _SyncClientSecretCredential
    from azure.identity.aio import ClientSecretCredential as _AsyncClientSecretCredential
except Exception:  # pragma: no cover - import guarded so the module always loads
    AzureKeyCredential = None  # type: ignore[assignment]
    _SyncClientSecretCredential = None  # type: ignore[assignment]
    _AsyncClientSecretCredential = None  # type: ignore[assignment]


def _has_service_principal(settings: Settings) -> bool:
    return bool(settings.azure_tenant_id and settings.azure_client_id and settings.azure_client_secret)


def build_search_credential(settings: Settings):
    """Async-capable credential for the aio SearchClient: service principal or key."""
    if _has_service_principal(settings):
        return _AsyncClientSecretCredential(
            tenant_id=settings.azure_tenant_id,
            client_id=settings.azure_client_id,
            client_secret=settings.azure_client_secret,
        )
    if not settings.search_api_key:
        raise ValueError(
            "no Azure Search credential: set the azure_* service principal or search_api_key"
        )
    return AzureKeyCredential(settings.search_api_key)


def search_bearer_token(settings: Settings) -> str | None:
    """A bearer token for the REST index API when a service principal is configured."""
    if not _has_service_principal(settings):
        return None
    credential = _SyncClientSecretCredential(
        tenant_id=settings.azure_tenant_id,
        client_id=settings.azure_client_id,
        client_secret=settings.azure_client_secret,
    )
    return credential.get_token(_SEARCH_SCOPE).token
