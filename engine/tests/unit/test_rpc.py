"""Unit tests for JSON-RPC 2.0 dispatcher and protocol framing."""

import pytest

from qa_engine.orchestrator.rpc import (
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    RPCDispatcher,
)


@pytest.mark.asyncio
async def test_rpc_successful_call():
    dispatcher = RPCDispatcher()

    async def echo_handler(params):
        return {"echo": params.get("msg")}

    dispatcher.register("test.echo", echo_handler)

    request = '{"jsonrpc": "2.0", "id": 1, "method": "test.echo", "params": {"msg": "hello"}}'
    response = await dispatcher.handle_payload(request)

    assert response is not None
    assert response.id == 1
    assert response.result == {"echo": "hello"}
    assert response.error is None


@pytest.mark.asyncio
async def test_rpc_method_not_found():
    dispatcher = RPCDispatcher()
    request = '{"jsonrpc": "2.0", "id": 2, "method": "unknown.method", "params": {}}'
    response = await dispatcher.handle_payload(request)

    assert response is not None
    assert response.id == 2
    assert response.error is not None
    assert response.error.code == METHOD_NOT_FOUND


@pytest.mark.asyncio
async def test_rpc_malformed_json():
    dispatcher = RPCDispatcher()
    request = '{"jsonrpc": "2.0", "id": 3, "method": incomplete...'
    response = await dispatcher.handle_payload(request)

    assert response is not None
    assert response.error is not None
    assert response.error.code == PARSE_ERROR


@pytest.mark.asyncio
async def test_rpc_notification_has_no_response():
    dispatcher = RPCDispatcher()
    received = []

    async def notif_handler(params):
        received.append(params)

    dispatcher.register("client.notify", notif_handler)

    # Notifications omit 'id'
    notification = '{"jsonrpc": "2.0", "method": "client.notify", "params": {"status": "ok"}}'
    response = await dispatcher.handle_payload(notification)

    assert response is None
    assert len(received) == 1
    assert received[0] == {"status": "ok"}
