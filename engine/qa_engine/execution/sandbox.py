"""Isolated subprocess execution sandbox with sanitized environment.

Enforces T2 & T3 controls:
- Executes commands strictly as argument arrays without a system shell (shell=False).
- Strips host tokens, credentials, and sensitive environment variables.
- Applies execution timeouts and full process-tree termination.
"""

import logging
import os
import subprocess  # nosec B404
import sys
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class SandboxedSubprocess:
    """Executes child processes with a cleaned environment and strict timeouts."""

    ALLOWED_ENV_VARS = {
        "PATH",
        "PYTHONPATH",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "HOMEDRIVE",
        "HOMEPATH",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "USERNAME",
        "HOME",
        "PLAYWRIGHT_BROWSERS_PATH",
        "APPDATA",
        "LOCALAPPDATA",
        "SESSIONNAME",
        # Required on Windows to locate installed branded browsers (Google Chrome, Edge).
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMW6432",
        "PROGRAMDATA",
        # Required on Linux/macOS for headed browser windows.
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "XAUTHORITY",
        "XDG_RUNTIME_DIR",
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

    @staticmethod
    def _kill_process_tree(proc: subprocess.Popen) -> None:
        """Terminate the child and every descendant (e.g. browsers launched by pytest)."""
        if proc.poll() is not None:
            return
        if sys.platform == "win32":
            system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
            taskkill = os.path.join(system_root, "System32", "taskkill.exe")
            subprocess.run(  # noqa: S603 # nosec B603
                [taskkill, "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                check=False,
            )
        else:
            proc.kill()

    @classmethod
    def run_sandboxed(
        cls,
        args: List[str],
        cwd: Path,
        timeout_seconds: int = 120,
        extra_env: Optional[Dict[str, str]] = None,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> Tuple[int, str, str]:
        """Run a process in sanitized environment with explicit arguments and timeout.

        When ``on_output`` is given, every stdout/stderr line is forwarded to it as soon
        as the child writes it, so long-running suites report progress live.
        """
        env = cls.sanitize_environment(extra_env)

        proc = subprocess.Popen(  # noqa: S603 # nosec B603
            args,
            cwd=str(cwd),
            env=env,
            shell=False,  # Enforces T3: zero shell execution
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        stdout_lines: List[str] = []
        stderr_lines: List[str] = []

        def pump(stream, sink: List[str]) -> None:
            for line in stream:
                sink.append(line)
                if on_output is not None:
                    try:
                        on_output(line.rstrip("\r\n"))
                    except Exception:  # noqa: BLE001
                        logger.exception("Output callback failed")
            stream.close()

        readers = [
            threading.Thread(target=pump, args=(proc.stdout, stdout_lines), daemon=True),
            threading.Thread(target=pump, args=(proc.stderr, stderr_lines), daemon=True),
        ]
        for reader in readers:
            reader.start()

        try:
            proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            cls._kill_process_tree(proc)
            proc.wait()
            for reader in readers:
                reader.join(timeout=5)
            return -1, "".join(stdout_lines), f"Process timed out after {timeout_seconds} seconds."

        for reader in readers:
            reader.join()
        return proc.returncode, "".join(stdout_lines), "".join(stderr_lines)
