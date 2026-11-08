"""Run Store manager for the QA Engine.

Manages run directory lifecycle, atomic file writes, path validation,
and persistence of all run artifacts in .qa-harness/runs/<run-id>/.
"""

import json
import tempfile
from pathlib import Path
from typing import Any, Optional, Union

from pydantic import BaseModel

from qa_engine.orchestrator.audit import AuditLogger
from qa_engine.security.paths import resolve_safe_path


class ScopeModel(BaseModel):
    start_url: str
    allowed_domains: list[str]
    environment: str = "test"  # "test", "staging", "production"
    credentials_ref: Optional[str] = None
    destructive_actions: str = "require_approval"
    max_pages: int = 25
    max_steps: int = 150
    rate_limit_rps: float = 2.0
    browsers: list[str] = ["chromium"]
    viewports: list[str] = ["desktop"]
    retries: int = 2
    data_classification: str = "synthetic"  # "synthetic", "sanitized"
    authorized_attestation: bool = False


class RunStore:
    """Encapsulates all persistent storage for a specific execution run."""

    def __init__(self, workspace_root: Union[str, Path], run_id: str):
        self.workspace_root = Path(workspace_root).resolve()
        self.run_id = run_id
        self.run_dir = self.workspace_root / ".qa-harness" / "runs" / self.run_id
        self._audit_logger: Optional[AuditLogger] = None
        self._ensure_layout()

    def _ensure_layout(self) -> None:
        """Create the mandatory folder hierarchy for this run."""
        subdirs = [
            self.run_dir / "testcases",
            self.run_dir / "scripts" / "pages",
            self.run_dir / "scripts" / "tests",
            self.run_dir / "results",
            self.run_dir / "evidence" / "screenshots",
            self.run_dir / "evidence" / "traces",
            self.run_dir / "evidence" / "har",
            self.run_dir / "evidence" / "logs",
            self.run_dir / "report",
        ]
        for d in subdirs:
            d.mkdir(parents=True, exist_ok=True)

    @property
    def audit(self) -> AuditLogger:
        if self._audit_logger is None:
            self._audit_logger = AuditLogger(self.run_dir / "audit.jsonl")
        return self._audit_logger

    def write_atomic(self, relative_path: Union[str, Path], content: str) -> Path:
        """Safely and atomically write content to a relative path within run_dir."""
        target_path = resolve_safe_path(self.run_dir, relative_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temporary file in the same directory, then atomic rename
        with tempfile.NamedTemporaryFile(
            "w", dir=target_path.parent, delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(content)
            temp_name = tmp.name

        Path(temp_name).replace(target_path)
        return target_path

    def write_json_atomic(self, relative_path: Union[str, Path], data: Any) -> Path:
        """Serialize data to JSON and atomically write to relative_path."""
        content = json.dumps(data, indent=2, ensure_ascii=False)
        return self.write_atomic(relative_path, content)

    def read_text(self, relative_path: Union[str, Path]) -> str:
        """Read text from a relative path within run_dir."""
        target_path = resolve_safe_path(self.run_dir, relative_path)
        if not target_path.exists():
            raise FileNotFoundError(f"File not found in run store: {relative_path}")
        return target_path.read_text(encoding="utf-8")

    def read_json(self, relative_path: Union[str, Path]) -> Any:
        """Read and deserialize JSON from a relative path within run_dir."""
        content = self.read_text(relative_path)
        return json.loads(content)

    def save_scope(self, scope: ScopeModel) -> Path:
        return self.write_json_atomic("scope.json", scope.model_dump())

    def load_scope(self) -> ScopeModel:
        data = self.read_json("scope.json")
        return ScopeModel.model_validate(data)
