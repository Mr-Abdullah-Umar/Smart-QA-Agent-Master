"""Evidence indexing and verification engine.

Implements Section 8.11 & Appendix B specifications:
- Scans run evidence directories: screenshots, traces, har, logs, dom.
- Assigns sequential verified evidence identifiers (e.g. EV-001, EV-002).
- Computes SHA-256 hashes of on-disk evidence files to ensure integrity.
- Provides strict citation verification so the investigation engine cannot
  cite hallucinated or non-existent evidence files.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

EVIDENCE_ID_REGEX = re.compile(r"^EV-\d{3,}$")


class EvidenceItem(BaseModel):
    evidence_id: str
    category: str  # e.g. "screenshot", "trace", "har", "console_log", "network_log", "error"
    relative_path: str
    description: str
    mime_type: str = "application/octet-stream"
    sha256: Optional[str] = None
    file_size_bytes: int = 0


class EvidenceIndex(BaseModel):
    items: Dict[str, EvidenceItem] = Field(default_factory=dict)

    def register_file(
        self,
        file_path: Path,
        base_dir: Path,
        category: str,
        description: str,
        mime_type: Optional[str] = None,
    ) -> EvidenceItem:
        """Register a physical on-disk file as a verified evidence item."""
        next_num = len(self.items) + 1
        ev_id = f"EV-{next_num:03d}"

        # Relative path from run directory or base directory
        try:
            rel_path = file_path.relative_to(base_dir).as_posix()
        except ValueError:
            rel_path = file_path.as_posix()

        # Compute SHA-256 and size
        sha256_hash = None
        size_bytes = 0
        if file_path.exists() and file_path.is_file():
            size_bytes = file_path.stat().st_size
            hasher = hashlib.sha256()
            with open(file_path, "rb") as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
            sha256_hash = hasher.hexdigest()

        # Infer mime type if not provided
        if not mime_type:
            suffix = file_path.suffix.lower()
            mime_map = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
                ".zip": "application/zip",
                ".har": "application/json",
                ".json": "application/json",
                ".log": "text/plain",
                ".txt": "text/plain",
                ".html": "text/html",
                ".yaml": "text/yaml",
                ".yml": "text/yaml",
            }
            mime_type = mime_map.get(suffix, "application/octet-stream")

        item = EvidenceItem(
            evidence_id=ev_id,
            category=category,
            relative_path=rel_path,
            description=description,
            mime_type=mime_type,
            sha256=sha256_hash,
            file_size_bytes=size_bytes,
        )
        self.items[ev_id] = item
        return item

    def register_inline_text(
        self,
        content: str,
        base_dir: Path,
        filename: str,
        category: str,
        description: str,
    ) -> EvidenceItem:
        """Save inline string evidence into evidence/logs/ and register."""
        logs_dir = base_dir / "evidence" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        target = logs_dir / filename
        target.write_text(content, encoding="utf-8")
        return self.register_file(
            file_path=target,
            base_dir=base_dir,
            category=category,
            description=description,
            mime_type="text/plain",
        )

    def verify_citation(self, evidence_id: str) -> bool:
        """Check if an evidence ID exists in this index and is valid."""
        clean_id = evidence_id.strip("[]")
        return clean_id in self.items

    def get_valid_citations(self, citations: List[str]) -> List[str]:
        """Filter a list of citations to only those verified in this index."""
        valid = []
        for c in citations:
            clean = c.strip("[]")
            if clean in self.items:
                valid.append(clean)
        return valid

    def scan_run_directory(self, run_dir: Path) -> None:
        """Scan standard evidence subdirectories inside run folder."""
        evidence_dir = run_dir / "evidence"
        if not evidence_dir.exists():
            return

        # Scan screenshots
        screenshots_dir = evidence_dir / "screenshots"
        if screenshots_dir.exists():
            for p in sorted(screenshots_dir.glob("*")):
                if p.is_file() and not self._is_already_registered(p, run_dir):
                    self.register_file(
                        p,
                        run_dir,
                        category="screenshot",
                        description=f"Screenshot captured at {p.name}",
                    )

        # Scan traces
        traces_dir = evidence_dir / "traces"
        if traces_dir.exists():
            for p in sorted(traces_dir.glob("*.zip")):
                if not self._is_already_registered(p, run_dir):
                    self.register_file(
                        p,
                        run_dir,
                        category="trace",
                        description=f"Playwright execution trace: {p.name}",
                    )

        # Scan HAR files
        har_dir = evidence_dir / "har"
        if har_dir.exists():
            for p in sorted(har_dir.glob("*.har")):
                if not self._is_already_registered(p, run_dir):
                    self.register_file(
                        p,
                        run_dir,
                        category="har",
                        description=f"HTTP Archive network capture: {p.name}",
                    )

        # Scan logs
        logs_dir = evidence_dir / "logs"
        if logs_dir.exists():
            for p in sorted(logs_dir.glob("*")):
                if p.is_file() and not self._is_already_registered(p, run_dir):
                    self.register_file(
                        p,
                        run_dir,
                        category="console_log",
                        description=f"Log file: {p.name}",
                    )

    def _is_already_registered(self, file_path: Path, base_dir: Path) -> bool:
        try:
            rel = file_path.relative_to(base_dir).as_posix()
        except ValueError:
            rel = file_path.as_posix()
        return any(item.relative_path == rel for item in self.items.values())

    def save(self, out_path: Path) -> None:
        """Persist evidence index to JSON."""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "EvidenceIndex":
        """Load evidence index from JSON."""
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.model_validate(data)
