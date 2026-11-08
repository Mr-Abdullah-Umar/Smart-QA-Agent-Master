"""Unit tests for ReviewManager, approval records, and post-approval tampering detection."""

from qa_engine.generation.testcases import TestCase, TestCaseCollection
from qa_engine.orchestrator.review import ReviewComment, ReviewManager
from qa_engine.orchestrator.run_store import RunStore


def test_review_manager_lifecycle_and_tamper_detection(tmp_path):
    store = RunStore(workspace_root=tmp_path, run_id="run-review-001")
    manager = ReviewManager(store)

    # 1. Draft Version 1
    tc1 = TestCase(
        tc_id="TC-001",
        title="Check Home Page",
        requirement_ref="REQ-HOME",
        steps=["Open homepage"],
        expected_result="Logo visible",
    )
    v1 = TestCaseCollection(version=1, testcases=[tc1])
    manager.save_version(v1)

    assert (store.run_dir / "testcases" / "v1.json").exists()
    assert (store.run_dir / "testcases" / "v1.md").exists()

    # 2. Reviewer requests changes -> Draft Version 2
    tc1_revised = tc1.model_copy(update={"steps": ["Open homepage", "Verify navigation menu"]})
    v2 = TestCaseCollection(version=2, testcases=[tc1_revised])
    comments = [ReviewComment(tc_id="TC-001", comment="Please add step for navigation menu")]

    diff = manager.record_revision(old_version=1, revised_collection=v2, comments=comments)
    assert len(diff.modified_cases) == 1
    assert (store.run_dir / "testcases" / "v2.json").exists()

    # 3. Approve Version 2 (Gate 1)
    record = manager.approve_version(version=2, approver="alice@qa.team")
    assert record.version == 2
    assert (store.run_dir / "approvals.json").exists()

    # Integrity verification must pass
    assert manager.verify_approved_hash() is True

    # 4. Simulate tampering with testcases/v2.json on disk
    v2_data = store.read_json("testcases/v2.json")
    v2_data["testcases"][0]["expected_result"] = "Tampered unauthorized expectation"
    store.write_json_atomic("testcases/v2.json", v2_data)

    # Integrity verification must fail
    assert manager.verify_approved_hash() is False
