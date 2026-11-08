"""Review and approval loop coordinator for Gate 1 governance.

Enforces Section 8.6 & T10 controls:
- Tracks incremental test case versions (v1, v2, ...).
- Ingests reviewer comments and records structural diffs.
- Binds approved test cases to a cryptographic SHA-256 hash in approvals.json.
- Verifies hash integrity prior to script generation or test execution.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

from qa_engine.generation.diff import TestCaseDiffEngine, VersionDiff
from qa_engine.generation.testcases import CoverageMatrix, TestCaseCollection
from qa_engine.orchestrator.run_store import RunStore


class ApprovalRecord(BaseModel):
    version: int
    approver: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    sha256_hash: str
    total_cases: int


class ReviewComment(BaseModel):
    tc_id: Optional[str] = None  # None indicates general comment for whole set
    comment: str
    author: str = "engineer"


class ReviewManager:
    """Coordinates versioning, comments, diffs, and cryptographic Gate 1 sign-off."""

    def __init__(self, run_store: RunStore):
        self.store = run_store

    def save_version(
        self,
        collection: TestCaseCollection,
        coverage_matrix: Optional[CoverageMatrix] = None,
    ) -> Path:
        """Save test cases version as JSON and Markdown in testcases/ folder."""
        v_num = collection.version
        json_path = f"testcases/v{v_num}.json"
        md_path = f"testcases/v{v_num}.md"

        self.store.write_json_atomic(json_path, collection.model_dump())
        self.store.write_atomic(md_path, collection.to_markdown())

        if coverage_matrix:
            self.store.write_json_atomic("coverage_matrix.json", coverage_matrix.model_dump())

        self.store.audit.log_event(
            stage="STAGE_4_TEST_DESIGN",
            event_type="TESTCASES_DRAFTED",
            actor="engine",
            details={
                "version": v_num,
                "total_cases": len(collection.testcases),
                "sha256_hash": collection.compute_sha256_hash(),
            },
        )
        return self.store.run_dir / json_path

    def load_version(self, version: int) -> TestCaseCollection:
        """Load specific test case version from disk."""
        data = self.store.read_json(f"testcases/v{version}.json")
        return TestCaseCollection.model_validate(data)

    def record_revision(
        self,
        old_version: int,
        revised_collection: TestCaseCollection,
        comments: Optional[List[ReviewComment]] = None,
    ) -> VersionDiff:
        """Save revised test cases, compute diff against previous version, and store diff."""
        old_collection = self.load_version(old_version)
        diff = TestCaseDiffEngine.compute_diff(old_collection, revised_collection)

        # Save new version
        self.save_version(revised_collection)

        # Save diff artifact
        diff_path = f"testcases/diff_v{old_version}_to_v{revised_collection.version}.json"
        self.store.write_json_atomic(diff_path, diff.model_dump())

        self.store.audit.log_event(
            stage="STAGE_5_REVIEW_LOOP",
            event_type="TESTCASES_REVISED",
            actor="engine",
            details={
                "old_version": old_version,
                "new_version": revised_collection.version,
                "diff_summary": diff.generate_summary(),
                "comments_count": len(comments) if comments else 0,
            },
        )
        return diff

    def approve_version(self, version: int, approver: str) -> ApprovalRecord:
        """Gate 1: Record cryptographic approval bound to canonical SHA-256 content hash."""
        collection = self.load_version(version)
        content_hash = collection.compute_sha256_hash()

        record = ApprovalRecord(
            version=version,
            approver=approver,
            sha256_hash=content_hash,
            total_cases=len(collection.testcases),
        )

        self.store.write_json_atomic("approvals.json", record.model_dump())

        # Update testcase status to approved
        for tc in collection.testcases:
            tc.status = "approved"
        self.store.write_json_atomic(f"testcases/v{version}.json", collection.model_dump())

        self.store.audit.log_event(
            stage="STAGE_5_REVIEW_LOOP",
            event_type="GATE_1_TESTCASES_APPROVED",
            actor=approver,
            details=record.model_dump(),
        )
        return record

    def verify_approved_hash(self) -> bool:
        """Verify that current approved testcases on disk exactly match approvals.json hash."""
        approval_file = self.store.run_dir / "approvals.json"
        if not approval_file.exists():
            return False

        record_data = self.store.read_json("approvals.json")
        record = ApprovalRecord.model_validate(record_data)

        collection = self.load_version(record.version)
        current_hash = collection.compute_sha256_hash()

        return current_hash == record.sha256_hash
