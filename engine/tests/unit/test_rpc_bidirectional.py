"""Engine -> extension requests over the stdio channel (LLM bridge and secret lookups)."""

import asyncio
import json

import pytest

from qa_engine.llm.bridge_provider import ExtensionBridgeProvider
from qa_engine.orchestrator.rpc import RemoteRPCError, StdioChannel


class LoopbackChannel(StdioChannel):
    def __init__(self, reply):
        super().__init__()
        self.sent = []
        self.reply = reply

    async def _write_raw(self, payload: str) -> None:
        message = json.loads(payload)
        self.sent.append(message)
        if "id" in message and "method" in message:
            asyncio.get_running_loop().call_soon(
                self.resolve_response, {"id": message["id"], **self.reply(message)}
            )


@pytest.mark.asyncio
async def test_bridge_provider_round_trip():
    channel = LoopbackChannel(
        lambda m: {
            "result": {
                "content": f"echo:{m['params']['messages'][0]['content']}",
                "model": "copilot/gpt",
            }
        }
    )
    llm = ExtensionBridgeProvider(channel)
    response = await llm.chat([{"role": "user", "content": "hi"}])
    assert response.content == "echo:hi"
    assert llm.model_label == "copilot/gpt"
    assert channel.sent[0]["method"] == "llm.chat"


@pytest.mark.asyncio
async def test_remote_error_is_raised():
    channel = LoopbackChannel(lambda m: {"error": {"code": -32000, "message": "No provider"}})
    with pytest.raises(RemoteRPCError, match="No provider"):
        await channel.request("llm.chat", {})
    assert channel.resolve_response({"id": "unknown", "result": 1}) is False
