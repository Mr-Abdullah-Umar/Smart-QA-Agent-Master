"""Unit tests for path confinement and security (T4 controls)."""

import pytest

from qa_engine.security.paths import PathSecurityError, resolve_safe_path


def test_safe_path_resolution(tmp_path):
    base_dir = tmp_path / "run_folder"
    base_dir.mkdir()

    safe_target = resolve_safe_path(base_dir, "testcases/v1.json")
    expected = (base_dir / "testcases" / "v1.json").resolve()
    assert safe_target == expected


def test_path_traversal_rejection(tmp_path):
    base_dir = tmp_path / "run_folder"
    base_dir.mkdir()

    # Attempting to escape run_folder via parent directory traversal
    with pytest.raises(PathSecurityError, match="escapes base directory"):
        resolve_safe_path(base_dir, "../../../secret.txt")


def test_absolute_path_outside_base(tmp_path):
    base_dir = tmp_path / "run_folder"
    base_dir.mkdir()
    outside_dir = tmp_path / "other_folder" / "file.txt"

    with pytest.raises(PathSecurityError):
        resolve_safe_path(base_dir, str(outside_dir))
