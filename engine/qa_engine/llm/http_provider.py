"""API-key LLM provider for running the engine without VS Code (CLI, CI pipelines).

Configured only through environment variables, so keys never touch files or arguments:

    QA_AI_PROVIDER          openai | azure-openai | anthropic | gemini | github-models |
                            openai-compatible
    QA_AI_API_KEY           API key (github-models also accepts GITHUB_TOKEN)
    QA_AI_MODEL             model ID (Azure: deployment name; GitHub Models: e.g. openai/gpt-4.1)
    QA_AI_BASE_URL          endpoint (required for azure-openai and openai-compatible)
    QA_AI_AZURE_API_VERSION Azure REST api-version (default 2024-10-21)

Endpoints must be HTTPS and pass the same network policy as test targets.
"""

import asyncio
import json
import urllib.error
import urllib.request
from typing import Any, AsyncIterator, Dict, List, Mapping, Optional, Tuple
from urllib.parse import quote, urlparse

from qa_engine.llm.provider import LLMProvider, LLMResponse, ToolDefinition
from qa_engine.security.ssrf import validate_destination_url

DEFAULT_BASE_URLS: Dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "github-models": "https://models.github.ai/inference",
}
PROVIDER_IDS = (
    "openai",
    "azure-openai",
    "anthropic",
    "gemini",
    "github-models",
    "openai-compatible",
)


class LLMConfigError(ValueError):
    """Raised when the API-key provider is misconfigured."""


class HttpLLMProvider(LLMProvider):
    """Chat completions over HTTPS for OpenAI-style, Azure OpenAI, and Anthropic APIs."""

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str,
        base_url: Optional[str] = None,
        azure_api_version: str = "2024-10-21",
        timeout_seconds: float = 180.0,
    ):
        if provider not in PROVIDER_IDS:
            raise LLMConfigError(
                f"Unknown AI provider '{provider}'. Use one of: {', '.join(PROVIDER_IDS)}."
            )
        if not api_key:
            raise LLMConfigError(f"Set QA_AI_API_KEY for the {provider} provider.")
        if not model:
            raise LLMConfigError("Set QA_AI_MODEL to the model (or Azure deployment) to use.")
        base = (base_url or DEFAULT_BASE_URLS.get(provider, "")).rstrip("/")
        if not base:
            raise LLMConfigError(f"Set QA_AI_BASE_URL for the {provider} provider.")
        if urlparse(base).scheme != "https":
            raise LLMConfigError(
                "AI endpoints must use https:// so the key is never sent in clear."
            )
        host = (urlparse(base).hostname or "").lower()
        ok, reason = validate_destination_url(base, [host], resolve_dns=True)
        if not ok:
            raise LLMConfigError(f"AI endpoint rejected by network policy: {reason}")
        self.provider = provider
        self.model = model
        self.base_url = base
        self.azure_api_version = azure_api_version
        self.timeout_seconds = timeout_seconds
        self._api_key = api_key
        self.model_label = f"{provider}/{model}"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Optional["HttpLLMProvider"]:
        """Provider configured by QA_AI_* variables, or None when QA_AI_PROVIDER is unset."""
        provider = (env.get("QA_AI_PROVIDER") or "").strip().lower()
        if not provider or provider == "none":
            return None
        key = env.get("QA_AI_API_KEY") or ""
        if not key and provider == "github-models":
            key = env.get("GITHUB_TOKEN") or ""
        return cls(
            provider=provider,
            api_key=key.strip(),
            model=(env.get("QA_AI_MODEL") or "").strip(),
            base_url=(env.get("QA_AI_BASE_URL") or "").strip() or None,
            azure_api_version=(env.get("QA_AI_AZURE_API_VERSION") or "2024-10-21").strip(),
        )

    async def initialize(self) -> None:
        return None

    async def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        content = await asyncio.to_thread(self._chat_sync, messages, temperature)
        return LLMResponse(content=content, finish_reason="stop")

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        response = await self.chat(messages, tools, temperature)
        yield response.content or ""

    # ------------------------------------------------------------------ request building

    def build_request(
        self, messages: List[Dict[str, str]], temperature: Optional[float]
    ) -> Tuple[str, Dict[str, str], Dict[str, Any]]:
        """URL, headers, and JSON body for one chat call (temperature None = omit)."""
        headers = {"Content-Type": "application/json"}
        if self.provider == "anthropic":
            system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
            body: Dict[str, Any] = {
                "model": self.model,
                "max_tokens": 8192,
                "messages": [
                    {"role": m["role"], "content": m["content"]}
                    for m in messages
                    if m["role"] != "system"
                ],
            }
            if system:
                body["system"] = system
            if temperature is not None:
                body["temperature"] = temperature
            headers.update({"x-api-key": self._api_key, "anthropic-version": "2023-06-01"})
            return f"{self.base_url}/messages", headers, body

        body = {"messages": messages}
        if temperature is not None:
            body["temperature"] = temperature
        if self.provider == "azure-openai":
            url = (
                f"{self.base_url}/openai/deployments/{quote(self.model, safe='')}"
                f"/chat/completions?api-version={quote(self.azure_api_version, safe='')}"
            )
            headers["api-key"] = self._api_key
            return url, headers, body
        body["model"] = self.model
        headers["Authorization"] = f"Bearer {self._api_key}"
        return f"{self.base_url}/chat/completions", headers, body

    @staticmethod
    def parse_content(provider: str, data: Dict[str, Any]) -> str:
        if provider == "anthropic":
            parts = data.get("content") or []
            text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
        else:
            choices = data.get("choices") or [{}]
            text = (choices[0].get("message") or {}).get("content")
        if not isinstance(text, str):
            raise RuntimeError(f"The {provider} provider returned no message content.")
        return text

    def _chat_sync(self, messages: List[Dict[str, str]], temperature: float) -> str:
        try:
            return self._post(messages, temperature)
        except _TemperatureRejected:
            # Some reasoning models only accept their default temperature.
            return self._post(messages, None)

    def _post(self, messages: List[Dict[str, str]], temperature: Optional[float]) -> str:
        url, headers, body = self.build_request(messages, temperature)
        request = urllib.request.Request(  # noqa: S310 - https enforced in __init__
            url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
        )
        opener = urllib.request.urlopen
        try:
            with opener(request, timeout=self.timeout_seconds) as response:  # noqa: S310  # nosec B310
                data = json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            if exc.code == 400 and temperature is not None and "temperature" in detail:
                raise _TemperatureRejected() from exc
            raise RuntimeError(f"{self.provider} returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Could not reach the {self.provider} endpoint: {exc.reason}"
            ) from exc
        return self.parse_content(self.provider, data)


class _TemperatureRejected(Exception):
    pass
