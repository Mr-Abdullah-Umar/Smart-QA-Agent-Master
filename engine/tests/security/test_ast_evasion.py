"""Security Penetration: AST Evasion and Malicious Code Detection (Appendix E Checklist).

Verifies T3 controls:
- Strict AST static analysis rejecting prohibited imports, dynamic execution (eval, exec),
  process spawning, file system access outside run data, and non-deterministic sleeps.
"""

import pytest

from qa_engine.generation.validator import ASTSecurityValidator

EVASION_TEST_CASES = [
    (
        "Banned import: socket",
        """
import socket
import pytest

@pytest.mark.tc("TC-001")
def test_socket_exfiltration():
    pass
""",
        "Prohibited import 'socket'",
    ),
    (
        "Banned import: subprocess",
        """
import subprocess
import pytest

@pytest.mark.tc("TC-002")
def test_subprocess_execution():
    pass
""",
        "Prohibited import 'subprocess'",
    ),
    (
        "Banned function call: eval",
        """
import pytest

@pytest.mark.tc("TC-003")
def test_dynamic_eval():
    eval("1 + 1")
""",
        "Prohibited function call 'eval()'",
    ),
    (
        "Banned function call: exec",
        """
import pytest

@pytest.mark.tc("TC-004")
def test_dynamic_exec():
    exec("x = 10")
""",
        "Prohibited function call 'exec()'",
    ),
    (
        "Banned function call: open",
        """
import pytest

@pytest.mark.tc("TC-005")
def test_file_read():
    with open("/etc/passwd", "r") as f:
        pass
""",
        "Prohibited function call 'open()'",
    ),
    (
        "Banned timing: time.sleep()",
        """
import time
import pytest

@pytest.mark.tc("TC-006")
def test_brittle_sleep():
    time.sleep(5)
""",
        "'time.sleep()' is banned",
    ),
    (
        "Missing test traceability mark",
        """
import pytest

def test_missing_traceability():
    assert True
""",
        "missing @pytest.mark.tc('TC-ID')",
    ),
]


@pytest.mark.parametrize("title,code,expected_error", EVASION_TEST_CASES)
def test_ast_security_evasion_attempts(title, code, expected_error):
    """Verify that ASTSecurityValidator intercepts each evasion vector."""
    result = ASTSecurityValidator.validate_script(code)
    assert not result.is_valid, f"Expected validator to fail for: {title}"
    assert any(expected_error.lower() in err.lower() for err in result.errors), (
        f"Expected '{expected_error}' in {result.errors}"
    )


def test_valid_playwright_test_script_passes():
    """Verify that clean, compliant Playwright test scripts pass validation."""
    clean_code = """
import pytest
from playwright.sync_api import Page, expect

@pytest.mark.tc("TC-LOGIN-001")
def test_login_success(page: Page):
    page.goto("https://example.com/login")
    page.locator("input#username").fill("alice")
    page.locator("input#password").fill("Secret123!")
    page.locator("button#submit").click()
    expect(page.locator("h1")).to_have_text("Welcome, Alice")
"""
    result = ASTSecurityValidator.validate_script(clean_code)
    assert result.is_valid, f"Expected valid script to pass, but got errors: {result.errors}"
