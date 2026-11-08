"""Mock LLM Provider for deterministic offline testing and CI workflows."""

import asyncio
from typing import AsyncIterator, Callable, Dict, List, Optional

from qa_engine.llm.provider import LLMProvider, LLMResponse, ToolCall, ToolDefinition


class MockLLMProvider(LLMProvider):
    """Deterministic reasoning engine mock."""

    def __init__(
        self,
        canned_response: Optional[str] = None,
        canned_tool_calls: Optional[List[ToolCall]] = None,
        custom_responder: Optional[Callable[[List[Dict[str, str]]], LLMResponse]] = None,
    ):
        self.canned_response = canned_response or "Mock reasoning response."
        self.canned_tool_calls = canned_tool_calls or []
        self.custom_responder = custom_responder
        self.recorded_messages: List[List[Dict[str, str]]] = []
        self.is_initialized = False

    async def initialize(self) -> None:
        self.is_initialized = True

    def set_mock_response(self, response: str) -> None:
        """Set or update the canned mock response string."""
        self.canned_response = response

    async def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        self.recorded_messages.append(messages)
        if self.custom_responder:
            return self.custom_responder(messages)
        return LLMResponse(
            content=self.canned_response,
            tool_calls=self.canned_tool_calls if self.canned_tool_calls else None,
            finish_reason="stop",
        )

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        self.recorded_messages.append(messages)
        response_text = self.canned_response
        for token in response_text.split(" "):
            await asyncio.sleep(0.001)
            yield token + " "
