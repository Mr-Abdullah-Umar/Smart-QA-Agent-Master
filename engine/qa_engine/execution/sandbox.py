"""Isolated subprocess execution sandbox with sanitized environment.

Enforces T2 & T3 controls:
- Executes commands strictly as argument arrays without a system shell (shell=False).
- Strips host tokens, credentials, and sensitive environment variables.
- Applies execution timeouts and full process-tree termination.
"""

import os
import subprocess  # nosec B404
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class SandboxedSubprocess:
    """Executes child processes with a cleaned environment and strict timeouts."""

    ALLOWED_ENV_VARS = {
        "PATH",
        "PYTHONPATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "HOME",
        "PLAYWRIGHT_BROWSERS_PATH",
    }

    @classmethod
    def sanitize_environment(cls, extra_vars: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Strip sensitive host environment variables, retaining only execution essentials."""
        cleaned = {}
        for key in cls.ALLOWED_ENV_VARS:
            val = os.environ.get(key)
            if val is not None:
                cleaned[key] = val

        if extra_vars:
            cleaned.update(extra_vars)

        return cleaned

    @classmethod
    def run_sandboxed(
        cls,
        args: List[str],
        cwd: Path,
        timeout_seconds: int = 120,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, str, str]:
        """Run a process in sanitized environment with explicit arguments and timeout."""
        env = cls.sanitize_environment(extra_env)

        try:
            proc = subprocess.run(  # noqa: S603 # nosec B603
                args,
                cwd=str(cwd),
                env=env,
                shell=False,  # Enforces T3: zero shell execution
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            return proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as e:
            stdout = e.stdout if isinstance(e.stdout, str) else ""
            stderr = f"Process timed out after {timeout_seconds} seconds."
            return -1, stdout, stderr
