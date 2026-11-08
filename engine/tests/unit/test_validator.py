"""Unit tests for AST Security Validator (T2 controls)."""

from qa_engine.generation.validator import ScriptValidator


def test_valid_generated_script_passes():
    valid_code = """
import pytest
from playwright.sync_api import Page, expect
from pages.login import LoginPage

@pytest.mark.tc("TC-AUTH-001")
def test_login_flow(page: Page, base_url: str):
    page.goto(base_url)
    expect(page.locator("h1")).to_be_visible()
"""
    is_valid, errors = ScriptValidator.validate_code(valid_code, approved_tc_ids={"TC-AUTH-001"})
    assert is_valid is True
    assert len(errors) == 0


def test_banned_imports_rejected():
    malicious_imports = [
        "import os\nos.system('dir')",
        "import subprocess\nsubprocess.run(['dir'])",
        "import socket\ns = socket.socket()",
        "import requests\nrequests.get('https://evil.com')",
        "import shutil\nshutil.rmtree('/')",
        "import ctypes",
        "import pickle",
    ]

    for code in malicious_imports:
        is_valid, errors = ScriptValidator.validate_code(code)
        assert is_valid is False
        assert any("Prohibited import" in err or "Prohibited" in err for err in errors)


def test_banned_eval_exec_rejected():
    code_eval = "def test_eval():\n    eval('1 + 1')"
    is_valid, errors = ScriptValidator.validate_code(code_eval)
    assert is_valid is False
    assert any("Prohibited function call 'eval()'" in err for err in errors)

    code_exec = "def test_exec():\n    exec('x = 2')"
    is_valid, errors = ScriptValidator.validate_code(code_exec)
    assert is_valid is False
    assert any("Prohibited function call 'exec()'" in err for err in errors)


def test_banned_time_sleep_rejected():
    code_sleep = """
import time
def test_wait():
    time.sleep(5)
"""
    is_valid, errors = ScriptValidator.validate_code(code_sleep)
    assert is_valid is False
    assert any("'time.sleep()' is banned" in err for err in errors)


def test_unapproved_tc_id_traceability_rejection():
    code = """
import pytest
from playwright.sync_api import Page

@pytest.mark.tc("TC-UNAPPROVED-999")
def test_unapproved(page: Page):
    pass
"""
    is_valid, errors = ScriptValidator.validate_code(code, approved_tc_ids={"TC-APPROVED-001"})
    assert is_valid is False
    assert any("unapproved test case IDs" in err for err in errors)

