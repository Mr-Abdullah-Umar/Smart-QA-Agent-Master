"""Abstract LLM Provider interface for the QA Engine reasoning layer.

Insulates the engine from changes in underlying provider libraries (such as
the preview GitHub Copilot SDK) and allows swapping in mock providers for CI/CD.
"""

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List, Optional

from pydantic import BaseModel, Field


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    call_id: str
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    finish_reason: Optional[str] = "stop"


class LLMProvider(ABC):
    """Abstract reasoning provider interface."""

    @abstractmethod
    async def initialize(self) -> None:
        """Perform initialization handshake with the model backend."""
        pass

    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """Execute a non-streaming turn with the model."""
        pass

    @abstractmethod
    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        """Stream model response tokens progressively."""
        pass
