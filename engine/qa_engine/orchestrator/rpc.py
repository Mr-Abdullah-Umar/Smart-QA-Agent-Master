"""JSON-RPC 2.0 communication layer for the QA Engine over standard input/output.

Adheres strictly to JSON-RPC 2.0 specifications. No TCP sockets or network
listeners are opened. All messages are newline-delimited JSON.
"""

import asyncio
import json
import sys
from typing import Any, Callable, Coroutine, Dict, Optional, Union

from pydantic import BaseModel, Field


class RPCError(BaseModel):
    code: int
    message: str
    data: Optional[Any] = None


class RPCRequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    params: Optional[Dict[str, Any]] = Field(default_factory=dict)
    id: Optional[Union[str, int]] = None  # None for notifications


class RPCResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None
    result: Optional[Any] = None
    error: Optional[RPCError] = None


class RPCNotification(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    params: Optional[Dict[str, Any]] = Field(default_factory=dict)


# Standard JSON-RPC 2.0 Error Codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
SERVER_ERROR_RESERVED = -32000


class RPCDispatcher:
    """Manages method registration, schema validation, and bidirectional message exchange."""

    def __init__(self):
        self._handlers: Dict[str, Callable[[Dict[str, Any]], Coroutine[Any, Any, Any]]] = {}

    def register(
        self, method: str, handler: Callable[[Dict[str, Any]], Coroutine[Any, Any, Any]]
    ) -> None:
        """Register an async handler function for a JSON-RPC method."""
        self._handlers[method] = handler

    async def handle_payload(self, raw_line: str) -> Optional[RPCResponse]:
        """Parse raw JSON line, validate request, and dispatch to registered handler."""
        raw_line = raw_line.strip()
        if not raw_line:
            return None

        try:
            data = json.loads(raw_line)
        except Exception as e:
            return RPCResponse(
                id=None, error=RPCError(code=PARSE_ERROR, message=f"Parse error: {e}")
            )

        try:
            req = RPCRequest.model_validate(data)
        except Exception as e:
            msg_id = data.get("id") if isinstance(data, dict) else None
            return RPCResponse(
                id=msg_id, error=RPCError(code=INVALID_REQUEST, message=f"Invalid Request: {e}")
            )

        # Check if method exists
        handler = self._handlers.get(req.method)
        if not handler:
            if req.id is not None:
                return RPCResponse(
                    id=req.id,
                    error=RPCError(
                        code=METHOD_NOT_FOUND, message=f"Method not found: '{req.method}'"
                    ),
                )
            return None

        # Execute handler
        try:
            params = req.params or {}
            result = await handler(params)
            if req.id is not None:
                return RPCResponse(id=req.id, result=result)
            return None
        except Exception as e:
            if req.id is not None:
                return RPCResponse(
                    id=req.id,
                    error=RPCError(
                        code=INTERNAL_ERROR, message=f"Internal error executing '{req.method}': {e}"
                    ),
                )
            return None


class StdioChannel:
    """Async wrapper around sys.stdin and sys.stdout for line-delimited JSON-RPC.

    Uses an executor thread for reading sys.stdin to guarantee cross-platform
    compatibility across Windows, Linux, and macOS without IOCP pipe handle errors.
    """

    def __init__(self):
        self._writer_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Portable initialization."""
        pass

    async def read_line(self) -> Optional[str]:
        loop = asyncio.get_running_loop()
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            return None
        return line

    async def send_response(self, response: RPCResponse) -> None:
        """Write JSON-RPC response to stdout followed by newline."""
        payload = response.model_dump_json(exclude_none=True)
        await self._write_raw(payload)

    async def send_notification(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        """Send JSON-RPC notification to stdout (engine -> extension)."""
        notif = RPCNotification(method=method, params=params or {})
        payload = notif.model_dump_json(exclude_none=True)
        await self._write_raw(payload)

    async def _write_raw(self, payload: str) -> None:
        async with self._writer_lock:
            sys.stdout.write(payload + "\n")
            sys.stdout.flush()
