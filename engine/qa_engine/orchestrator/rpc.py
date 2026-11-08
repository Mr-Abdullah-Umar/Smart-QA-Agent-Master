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


class RemoteRPCError(Exception):
    """Raised when the extension answers an engine-initiated request with an error."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


class StdioChannel:
    """Async wrapper around sys.stdin and sys.stdout for line-delimited JSON-RPC.

    Uses an executor thread for reading sys.stdin to guarantee cross-platform
    compatibility across Windows, Linux, and macOS without IOCP pipe handle errors.
    Supports both directions: extension -> engine requests are dispatched by the server,
    engine -> extension requests (e.g. LLM calls, secret lookups) await matching responses.
    """

    def __init__(self):
        self._writer_lock = asyncio.Lock()
        self._pending: Dict[str, asyncio.Future] = {}
        self._next_request_id = 1

    async def request(
        self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 300.0
    ) -> Any:
        """Send an engine -> extension request and wait for its response."""
        request_id = f"engine-{self._next_request_id}"
        self._next_request_id += 1
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
        )
        try:
            await self._write_raw(payload)
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending.pop(request_id, None)

    def resolve_response(self, message: Dict[str, Any]) -> bool:
        """Complete a pending engine-initiated request. Returns False if unknown."""
        future = self._pending.get(str(message.get("id")))
        if future is None or future.done():
            return False
        error = message.get("error")
        if error:
            future.set_exception(
                RemoteRPCError(int(error.get("code", INTERNAL_ERROR)), str(error.get("message")))
            )
        else:
            future.set_result(message.get("result"))
        return True

    async def initialize(self) -> None:
        """Force UTF-8 pipes (Windows defaults to the ANSI code page)."""
        for stream in (sys.stdin, sys.stdout):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")

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
