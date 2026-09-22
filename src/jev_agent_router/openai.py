"""Backward-compatible OpenAI structured-output fallback (no SDK required)."""

import httpx
from .llm import ChatJSONFallback


class OpenAIJSONFallback(ChatJSONFallback):
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30,
    ):
        super().__init__(model=model, api_key=api_key, client=client, timeout=timeout)
