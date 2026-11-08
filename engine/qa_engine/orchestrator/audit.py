"""Tamper-evident, hash-chained audit logging for the QA Engine.

Enforces accountability and plan integrity. Every significant action
and gate approval is written to an append-only JSON Lines file (audit.jsonl)
where each entry includes the SHA-256 hash of the preceding entry.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field


class AuditEntry(BaseModel):
    entry_id: int
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    stage: str
    event_type: str
    actor: str  # "engineer", "engine", "model"
    details: Dict[str, Any] = Field(default_factory=dict)
    prev_hash: str
    sha256_hash: str = ""

    def compute_hash(self) -> str:
        """Compute SHA-256 of canonical JSON representation excluding sha256_hash itself."""
        payload = {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp,
            "stage": self.stage,
            "event_type": self.event_type,
            "actor": self.actor,
            "details": self.details,
            "prev_hash": self.prev_hash,
        }
        canonical_str = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()


class AuditLogger:
    GENESIS_HASH = "0" * 64

    def __init__(self, log_path: Path):
        self.log_path = Path(log_path)
        self.last_hash = self.GENESIS_HASH
        self.current_entry_id = 0
        self._initialize()

    def _initialize(self) -> None:
        """Read existing entries if resuming a run to discover the current state of the chain."""
        if self.log_path.exists():
            entries = self.read_entries()
            if entries:
                last_entry = entries[-1]
                self.last_hash = last_entry.sha256_hash
                self.current_entry_id = last_entry.entry_id
        else:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_event(
        self,
        stage: str,
        event_type: str,
        actor: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEntry:
        """Append a new hash-chained audit entry to audit.jsonl."""
        self.current_entry_id += 1
        entry = AuditEntry(
            entry_id=self.current_entry_id,
            stage=stage,
            event_type=event_type,
            actor=actor,
            details=details or {},
            prev_hash=self.last_hash,
        )
        entry.sha256_hash = entry.compute_hash()
        self.last_hash = entry.sha256_hash

        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")

        return entry

    def read_entries(self) -> List[AuditEntry]:
        """Read and parse all entries from the audit log."""
        if not self.log_path.exists():
            return []

        entries: List[AuditEntry] = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(AuditEntry.model_validate_json(line))
        return entries

    @classmethod
    def verify_log_file(cls, log_path: Path) -> Tuple[bool, Optional[str]]:
        """Verify the integrity of an audit.jsonl file.

        Returns (True, None) if completely intact, or (False, error_message)
        if any entry was modified, inserted, reordered, or deleted.
        """
        if not log_path.exists():
            return True, None

        expected_prev_hash = cls.GENESIS_HASH
        expected_entry_id = 1

        with open(log_path, "r", encoding="utf-8") as f:
            for line_idx, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = AuditEntry.model_validate_json(line)
                except Exception as e:
                    return False, f"Line {line_idx}: Invalid JSON entry schema: {e}"

                if entry.entry_id != expected_entry_id:
                    msg = (
                        f"Line {line_idx}: Non-sequential entry_id: "
                        f"expected {expected_entry_id}, got {entry.entry_id}"
                    )
                    return False, msg

                if entry.prev_hash != expected_prev_hash:
                    msg = (
                        f"Line {line_idx}: Broken hash link: "
                        f"expected prev_hash '{expected_prev_hash}', got '{entry.prev_hash}'"
                    )
                    return False, msg

                computed_hash = entry.compute_hash()
                if entry.sha256_hash != computed_hash:
                    msg = (
                        f"Line {line_idx}: Tampered content: "
                        f"recorded hash '{entry.sha256_hash}' != computed hash '{computed_hash}'"
                    )
                    return False, msg

                expected_prev_hash = entry.sha256_hash
                expected_entry_id += 1

        return True, None
