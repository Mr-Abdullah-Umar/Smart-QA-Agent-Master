"""Deny-by-default tool permission policy for model-driven tool calls.

Enforces T1, T2, T8 controls:
- Model requests cannot execute arbitrary tools.
- Only tools explicitly listed in Appendix C are permitted.
- Never uses blanket approve-all permissions.

Model access itself goes through `ExtensionBridgeProvider` (GitHub Copilot or an API-key
provider configured in VS Code) or `HttpLLMProvider` (API key from the environment).
"""

from typing import Set

ALLOWED_APPENDIX_C_TOOLS: Set[str] = {
    "read_requirement",
    "get_site_profile",
    "browser_navigate",
    "browser_snapshot",
    "browser_click",
    "browser_fill",
    "browser_select",
    "browser_press_key",
    "browser_wait_for",
    "browser_screenshot",
    "submit_analysis",
    "submit_testcases",
    "submit_scripts",
    "submit_investigation",
}


class PermissionDeniedError(Exception):
    """Raised when an unapproved tool call is attempted by the reasoning layer."""


class CopilotPermissionHandler:
    """Deny-by-default permission checker for tool calls."""

    @classmethod
    def verify_tool_permission(cls, tool_name: str) -> bool:
        return tool_name in ALLOWED_APPENDIX_C_TOOLS
