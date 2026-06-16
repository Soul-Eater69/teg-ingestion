"""LLM gateway integration: client protocol + IDP gateway implementation."""

from teg.integrations.llm.client import LLMClient
from teg.integrations.llm.idp_gateway import IdpLLMClient, LLMError, build_llm_client

__all__ = ["LLMClient", "IdpLLMClient", "LLMError", "build_llm_client"]
