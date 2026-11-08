"""Unit tests for SandboxedSubprocess environment sanitization and timeouts (T2/T3 controls)."""

import os
import sys

from qa_engine.execution.sandbox import SandboxedSubprocess


def test_environment_sanitization():
    # Set a sensitive dummy variable
    os.environ["INTERNAL_SENSITIVE_VAR"] = "super-confidential-value"

    cleaned = SandboxedSubprocess.sanitize_environment()

    # Sensitive variable must be stripped
    assert "INTERNAL_SENSITIVE_VAR" not in cleaned

    # Essential variables must be retained
    assert "PATH" in cleaned


def test_sandboxed_subprocess_execution(tmp_path):
    code, stdout, stderr = SandboxedSubprocess.run_sandboxed(
        args=[sys.executable, "-c", "print('sandbox execution successful')"],
        cwd=tmp_path,
        timeout_seconds=5,
    )

    assert code == 0
    assert "sandbox execution successful" in stdout


def test_sandboxed_subprocess_timeout(tmp_path):
    code, stdout, stderr = SandboxedSubprocess.run_sandboxed(
        args=[sys.executable, "-c", "import time; time.sleep(10)"],
        cwd=tmp_path,
        timeout_seconds=1,
    )

    assert code == -1
    assert "timed out" in stderr
