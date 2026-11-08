"""Unit tests for LLMProvider abstraction and permission checking."""

import pytest

from qa_engine.llm.copilot_provider import CopilotPermissionHandler
from qa_engine.llm.mock_provider import MockLLMProvider


@pytest.mark.asyncio
async def test_mock_llm_provider_chat():
    provider = MockLLMProvider(canned_response="Analysis of requirements complete.")
    await provider.initialize()

    response = await provider.chat(messages=[{"role": "user", "content": "Analyze requirements"}])
    assert response.content == "Analysis of requirements complete."
    assert len(provider.recorded_messages) == 1


@pytest.mark.asyncio
async def test_mock_llm_provider_stream():
    provider = MockLLMProvider(canned_response="Step 1 Step 2")
    await provider.initialize()

    tokens = []
    async for token in provider.stream_chat(messages=[{"role": "user", "content": "Stream test"}]):
        tokens.append(token)

    assert "".join(tokens).strip() == "Step 1 Step 2"


def test_copilot_permission_handler_deny_by_default():
    # Tools in Appendix C must pass
    assert CopilotPermissionHandler.verify_tool_permission("read_requirement") is True
    assert CopilotPermissionHandler.verify_tool_permission("browser_navigate") is True
    assert CopilotPermissionHandler.verify_tool_permission("submit_testcases") is True

    # Banned / unapproved tools must be DENIED by default
    assert CopilotPermissionHandler.verify_tool_permission("execute_shell_command") is False
    assert CopilotPermissionHandler.verify_tool_permission("read_arbitrary_file") is False
    assert CopilotPermissionHandler.verify_tool_permission("eval_javascript") is False
    assert CopilotPermissionHandler.verify_tool_permission("download_internet_binary") is False
