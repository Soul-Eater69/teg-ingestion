"""Environment-driven configuration.

All config comes from the environment (or a local .env), prefixed TEG_. Secrets and
non-secrets share one .env for now; splitting non-secrets into config files can come
later. Inject a Settings instance; never read os.environ deep in the call tree.
"""

from __future__ import annotations

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TEG_", env_file=".env", extra="ignore")

    # Jira
    jira_base_url: str = ""
    jira_token: str = ""  # Personal Access Token (Bearer)
    jira_api_version: str = "2"
    jira_verify_ssl: bool = False
    jira_timeout_seconds: float = 30.0
    jira_value_stream_field: str = ""  # Business Value Stream customfield_#####; discovered if empty
    jira_value_stream_field_name: str = "Business Value Stream"  # display name used for discovery

    # Azure AI Search (one unified index; lane = entityType filter)
    search_endpoint: str = ""
    search_api_key: str = ""
    search_index: str = "idp_teg_data"
    search_vector_field: str = "content_vector"
    search_semantic_config: str = "teg-semantic"
    search_api_version: str = "2024-07-01"  # needs >=2024-07-01 for the vector + complex schema

    # Azure AD service principal (Search + Cosmos auth; falls back to the resource key). Reads the
    # TEG_ var or the org's AZURE_*_DEV name, whichever is set.
    azure_tenant_id: str = Field("", validation_alias=AliasChoices(
        "TEG_AZURE_TENANT_ID", "AZURE_TENANT_ID_DEV"))
    azure_client_id: str = Field("", validation_alias=AliasChoices(
        "TEG_AZURE_CLIENT_ID", "AZURE_CLIENT_ID_DEV"))
    azure_client_secret: str = Field("", validation_alias=AliasChoices(
        "TEG_AZURE_CLIENT_SECRET", "AZURE_CLIENT_SECRET_DEV"))

    # Cosmos (lineage, ground truth, governed catalogues). One container, partition key /sourceId,
    # entityType discriminates ER / Theme / ValueStream docs. Auth = service principal (azure_*)
    # if set, else cosmos_key. Each field reads the TEG_ var or the org's AZURE_COSMOS_* name.
    cosmos_endpoint: str = Field("", validation_alias=AliasChoices(
        "TEG_COSMOS_ENDPOINT", "AZURE_COSMOS_DB_URL"))
    cosmos_key: str = ""
    cosmos_database: str = Field("", validation_alias=AliasChoices(
        "TEG_COSMOS_DATABASE", "AZURE_COSMOS_DB_NAME"))
    cosmos_container: str = Field("theme-and-epic", validation_alias=AliasChoices(
        "TEG_COSMOS_CONTAINER", "AZURE_COSMOS_CONTAINER_NAME"))

    # LLM (IDP OpenAI-compatible gateway)
    llm_base_url: str = ""
    llm_completion_path: str = "/api/v1/chatcompletions"
    llm_model: str = "gpt-5-mini-idp"
    llm_app_id: str = ""
    llm_api_version: str = "2024-04-01-preview"
    llm_reasoning_effort: str = "low"
    llm_max_output_tokens: int | None = None
    llm_max_retries: int = 5  # retry 429/5xx/transient-network with exponential backoff + jitter
    llm_timeout_seconds: float = 60.0
    llm_verify_ssl: bool = False

    # IDP auth (token endpoint for the LLM gateway)
    idp_auth_url: str = ""
    idp_client_id: str = ""
    idp_client_secret: str = ""
    idp_user: str = ""
    idp_password: str = ""

    # Embeddings (same IDP gateway + auth as the LLM)
    embedding_model: str = "text-embedding-3-small-idp"  # native 1536 dims
    embedding_dimensions: int = 1536  # must equal the index content_vector dimensions
    embedding_path: str = "/api/v1/embeddings"
    embedding_api_version: str = "2024-06-01"

    # Condense (fallback path only; idea card is always used in full)
    # The real cap is the char/token budget, not a file count: kept content is greedy-packed up to
    # ~96k chars ≈ 24k tokens regardless of how many attachments there are. We DOWNLOAD up to 8
    # attachments; the budget then decides how much of them is kept.
    condense_doc_char_budget: int = 96_000  # ~24k tokens — total chars kept across fallback docs (the real cap)
    condense_max_attachments: int = 8  # how many attachments to DOWNLOAD + extract (budget caps content)
    condense_max_attachment_bytes: int = 10_000_000  # skip larger fallback files pre-download
    condense_min_doc_chars: int = 200  # drop fallback docs that extract to less than this

    @field_validator("llm_max_output_tokens", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        # A blank env value (TEG_LLM_MAX_OUTPUT_TOKENS=) means "unset", not "".
        return None if value == "" else value


def load_settings() -> Settings:
    return Settings()
