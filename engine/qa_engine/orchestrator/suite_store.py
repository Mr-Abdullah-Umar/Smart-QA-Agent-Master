"""Persistent library of approved test suites (one suite per module) for retest and regression.

Layout under `<workspace>/.qa-harness/suites/<slug>/`:
    suite.json              SuiteRecord (module, scope, current approved version, last run)
    requirement.md          Requirement + acceptance criteria (redacted)
    criteria.json           Parsed acceptance criteria [{id, text}]
    history.json            Every execution (initial, retest, regression)
    latest_results.json     Latest status per TC ID (drives "retest failed only")
    versions/vN/
        testcases.json/.md  Approved test case collection
        approval.json       Gate 1 record: approver, SHA-256 of cases and of scripts
        scripts/            Generated pages/ and tests/ (validated by the AST gate)

Before any re-execution the stored cases and scripts are re-hashed and re-validated, so a
suite edited on disk after approval is refused (T10 tamper protection).
"""

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field

from qa_engine.generation.testcases import TestCaseCollection
from qa_engine.generation.validator import ScriptValidator
from qa_engine.security.paths import resolve_safe_path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(module: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", module.lower()).strip("-")
    return slug[:48] or "module"


class SuiteIntegrityError(Exception):
    """Raised when stored cases or scripts no longer match their Gate 1 approval."""


class SuiteRunSummary(BaseModel):
    run_id: str
    run_type: str  # "initial", "update", "retest", "retest-failed", "regression"
    started_at: str = Field(default_factory=_now)
    triggered_by: str = ""
    version: int = 1
    total: int = 0
    passed: int = 0
    failed: int = 0
    flaky: int = 0
    blocked: int = 0
    skipped: int = 0
    duration_seconds: float = 0.0
    failed_tc_ids: List[str] = Field(default_factory=list)
    report_html: Optional[str] = None
    regression_id: Optional[str] = None
    environment: str = ""
    target_url: str = ""


class SuiteApproval(BaseModel):
    version: int
    approver: str
    timestamp: str = Field(default_factory=_now)
    sha256_hash: str
    scripts_sha256: str
    total_cases: int


class SuiteRecord(BaseModel):
    slug: str
    module: str
    start_url: str
    allowed_domains: List[str]
    environment: str
    design_mode: str = "ai"  # "ai" or "smoke"
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    created_by: str = ""
    current_version: int = 0
    total_cases: int = 0
    test_types: List[str] = Field(default_factory=list)
    required_secrets: List[str] = Field(default_factory=list)
    last_run: Optional[SuiteRunSummary] = None
    requirement_text: str = ""
    # Additional environments: name -> start URL (the default is `environment` / `start_url`).
    environments: Dict[str, str] = Field(default_factory=dict)


def hash_scripts(scripts_dir: Path) -> str:
    """SHA-256 over every generated test/page file (path + content), excluding caches."""
    digest = hashlib.sha256()
    for sub in ("tests", "pages"):
        base = scripts_dir / sub
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            digest.update(path.relative_to(scripts_dir).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def _copy_scripts(src: Path, dest: Path) -> None:
    for sub in ("tests", "pages"):
        target = dest / sub
        if target.exists():
            shutil.rmtree(target)
        if (src / sub).exists():
            shutil.copytree(src / sub, target, ignore=shutil.ignore_patterns("__pycache__"))


class SuiteStore:
    """Reads and writes the suite library inside the workspace."""

    def __init__(self, workspace_root: Union[str, Path]):
        self.root = Path(workspace_root).resolve() / ".qa-harness" / "suites"
        self.root.mkdir(parents=True, exist_ok=True)

    def suite_dir(self, slug: str) -> Path:
        return resolve_safe_path(self.root, slugify(slug))

    def _write_json(self, path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def _read_json(self, path: Path, default=None):
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def exists(self, slug: str) -> bool:
        return (self.suite_dir(slug) / "suite.json").exists()

    def load(self, slug: str) -> SuiteRecord:
        data = self._read_json(self.suite_dir(slug) / "suite.json")
        if data is None:
            raise FileNotFoundError(f"Suite '{slug}' does not exist.")
        return SuiteRecord.model_validate(data)

    def save_record(self, record: SuiteRecord) -> None:
        record.updated_at = _now()
        self._write_json(self.suite_dir(record.slug) / "suite.json", record.model_dump())

    def list(self) -> List[SuiteRecord]:
        records = []
        for path in sorted(self.root.glob("*/suite.json")):
            try:
                records.append(SuiteRecord.model_validate_json(path.read_text(encoding="utf-8")))
            except ValueError:
                continue
        return records

    def save_version(
        self,
        record: SuiteRecord,
        collection: TestCaseCollection,
        scripts_dir: Path,
        approver: str,
        requirement_md: str,
        criteria: List[Dict[str, str]],
        required_secrets: List[str],
    ) -> SuiteApproval:
        """Persist an approved, validated version and make it the suite's current version."""
        base = self.suite_dir(record.slug)
        version = record.current_version + 1
        vdir = base / "versions" / f"v{version}"
        vdir.mkdir(parents=True, exist_ok=True)

        stored = collection.model_copy(deep=True)
        stored.version = version
        for tc in stored.testcases:
            tc.version = version
            tc.status = "approved"
        _copy_scripts(scripts_dir, vdir / "scripts")

        approval = SuiteApproval(
            version=version,
            approver=approver,
            sha256_hash=stored.compute_sha256_hash(),
            scripts_sha256=hash_scripts(vdir / "scripts"),
            total_cases=len(stored.testcases),
        )
        self._write_json(vdir / "testcases.json", stored.model_dump(mode="json"))
        (vdir / "testcases.md").write_text(stored.to_markdown(), encoding="utf-8")
        self._write_json(vdir / "approval.json", approval.model_dump())
        (base / "requirement.md").write_text(requirement_md, encoding="utf-8")
        self._write_json(base / "criteria.json", criteria)

        types = sorted({t for tc in stored.testcases for t in tc.test_types})
        record.current_version = version
        record.total_cases = len(stored.testcases)
        record.test_types = types
        record.required_secrets = required_secrets
        if not record.created_by:
            record.created_by = approver
        self.save_record(record)
        return approval

    def archive(self, slug: str, actor: str) -> Path:
        """Move a suite out of the library (kept under .qa-harness/archive/suites/)."""
        source = self.suite_dir(slug)
        if not (source / "suite.json").exists():
            raise FileNotFoundError(f"Suite '{slug}' does not exist.")
        archive_root = self.root.parent / "archive" / "suites"
        archive_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        target = resolve_safe_path(archive_root, f"{slugify(slug)}-{stamp}")
        shutil.move(str(source), str(target))
        log_path = archive_root / "archive-log.json"
        log = self._read_json(log_path, []) or []
        log.append({"slug": slugify(slug), "archived_to": target.name, "by": actor, "at": _now()})
        self._write_json(log_path, log)
        return target

    def load_version(self, slug: str, version: Optional[int] = None) -> TestCaseCollection:
        record = self.load(slug)
        v = version or record.current_version
        data = self._read_json(self.suite_dir(slug) / "versions" / f"v{v}" / "testcases.json")
        if data is None:
            raise FileNotFoundError(f"Suite '{slug}' has no version {v}.")
        return TestCaseCollection.model_validate(data)

    def load_approval(self, slug: str, version: int) -> SuiteApproval:
        data = self._read_json(self.suite_dir(slug) / "versions" / f"v{version}" / "approval.json")
        if data is None:
            raise SuiteIntegrityError(f"Suite '{slug}' v{version} has no Gate 1 approval.")
        return SuiteApproval.model_validate(data)

    def criteria(self, slug: str) -> List[Dict[str, str]]:
        return self._read_json(self.suite_dir(slug) / "criteria.json", []) or []

    def verify_integrity(self, slug: str) -> SuiteApproval:
        """Re-hash cases and scripts and re-run the AST gate; raise if anything changed."""
        record = self.load(slug)
        approval = self.load_approval(slug, record.current_version)
        collection = self.load_version(slug, record.current_version)
        if collection.compute_sha256_hash() != approval.sha256_hash:
            raise SuiteIntegrityError(
                f"Test cases of '{record.module}' changed after approval; re-approve the suite."
            )
        scripts = self.suite_dir(slug) / "versions" / f"v{record.current_version}" / "scripts"
        if hash_scripts(scripts) != approval.scripts_sha256:
            raise SuiteIntegrityError(
                f"Scripts of '{record.module}' changed after approval; regenerate the suite."
            )
        approved_ids = {tc.tc_id for tc in collection.testcases}
        for test_file in sorted((scripts / "tests").glob("test_*.py")):
            result = ScriptValidator.validate_script(
                test_file.read_text(encoding="utf-8"), approved_tc_ids=approved_ids
            )
            if not result.is_valid:
                raise SuiteIntegrityError(f"{test_file.name} failed the AST gate: {result.errors}")
        return approval

    def materialize_scripts(self, slug: str, dest_scripts_dir: Path) -> Path:
        """Copy the approved scripts into a run directory; returns its tests/ folder."""
        record = self.load(slug)
        src = self.suite_dir(slug) / "versions" / f"v{record.current_version}" / "scripts"
        _copy_scripts(src, dest_scripts_dir)
        return dest_scripts_dir / "tests"

    def latest_results(self, slug: str) -> Dict[str, str]:
        return self._read_json(self.suite_dir(slug) / "latest_results.json", {}) or {}

    def history(self, slug: str) -> List[SuiteRunSummary]:
        data = self._read_json(self.suite_dir(slug) / "history.json", []) or []
        return [SuiteRunSummary.model_validate(item) for item in data]

    def record_run(self, slug: str, summary: SuiteRunSummary, statuses: Dict[str, str]) -> None:
        base = self.suite_dir(slug)
        history = self._read_json(base / "history.json", []) or []
        history.append(summary.model_dump())
        self._write_json(base / "history.json", history[-200:])
        latest = self.latest_results(slug)
        latest.update(statuses)
        record = self.load(slug)
        valid_ids = {tc.tc_id for tc in self.load_version(slug, record.current_version).testcases}
        self._write_json(
            base / "latest_results.json", {k: v for k, v in latest.items() if k in valid_ids}
        )
        record.last_run = summary
        self.save_record(record)
