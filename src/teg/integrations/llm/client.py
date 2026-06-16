"""LLM client protocol.

The condense / VS / theme steps depend on this small async interface, not on a
concrete SDK. The caller passes a pydantic model as the output ``schema``; the
client requests provider-enforced structured output and returns a validated
instance. Output shapes are never described as JSON inside prompts. Tests inject a
fake; the real implementation wraps the provider SDK (structured output, prompt
caching, retries) and is configured from :class:`teg.config.settings.Settings`.
"""

from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


@runtime_checkable
class LLMClient(Protocol):
    async def complete(
        self,
        *,
        system: str,
        user: str,
        schema: type[ModelT],
    ) -> ModelT:
        """Run the prompt with ``schema`` as the structured-output contract.

        Returns a validated instance of ``schema``. The real client generates the
        provider schema from ``schema.model_json_schema(by_alias=True)``.
        """
        ...
