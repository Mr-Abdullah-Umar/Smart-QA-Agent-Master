"""LLM provider that delegates model calls to the VS Code extension over stdio JSON-RPC.

The extension owns provider selection and credentials (GitHub Copilot through the VS Code
Language Model API, or an API-key provider stored in the OS keychain). The engine never sees
API keys; it only sends messages and receives the model's text.
"""

from typing import AsyncIterator, Dict, List, Optional

from qa_engine.llm.provider import LLMProvider, LLMResponse, ToolDefinition
from qa_engine.orchestrator.rpc import StdioChannel


class ExtensionBridgeProvider(LLMProvider):
    """Routes chat requests to the extension's `llm.chat` handler."""

    def __init__(self, channel: StdioChannel, timeout_seconds: float = 300.0):
        self.channel = channel
        self.timeout_seconds = timeout_seconds
        self.model_label: Optional[str] = None

    async def initialize(self) -> None:
        return None

    async def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        result = await self.channel.request(
            "llm.chat",
            {"messages": messages, "temperature": temperature},
            timeout=self.timeout_seconds,
        )
        result = result or {}
        self.model_label = result.get("model") or self.model_label
        return LLMResponse(content=str(result.get("content", "")), finish_reason="stop")

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        response = await self.chat(messages, tools, temperature)
        yield response.content or ""
