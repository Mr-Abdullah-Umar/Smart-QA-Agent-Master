"""Path confinement and safety utilities for the QA Engine.

Enforces T4 controls: prevents path traversal and arbitrary file access
by ensuring all file read/write operations stay strictly within the designated run folder.
"""

from pathlib import Path
from typing import Union


class PathSecurityError(Exception):
    """Raised when a path traversal or unauthorized access attempt is detected."""

    pass


def resolve_safe_path(base_dir: Union[str, Path], user_path: Union[str, Path]) -> Path:
    """Resolve user_path relative to base_dir and guarantee it resides strictly inside base_dir.

    Resolves symlinks and rejects any relative traversal attempts (e.g. '../').
    """
    base = Path(base_dir).resolve()
    target = (base / user_path).resolve()

    # Verify that target is indeed inside base (is_relative_to in Python 3.9+)
    try:
        target.relative_to(base)
    except ValueError as e:
        raise PathSecurityError(
            f"Access denied: path '{user_path}' escapes base directory '{base}'"
        ) from e

    return target


def ensure_within_run_dir(run_dir: Union[str, Path], target_file: Union[str, Path]) -> Path:
    """Validate that target_file resides within the authorized run folder."""
    return resolve_safe_path(run_dir, target_file)
