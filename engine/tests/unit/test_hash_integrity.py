"""Unit tests for SHA-256 canonical approval hashing and tamper detection (T10 controls)."""

from qa_engine.generation.testcases import TestCase, TestCaseCollection


def test_hash_consistency_and_ordering():
    tc1 = TestCase(
        tc_id="TC-001",
        title="Login Valid",
        requirement_ref="REQ-1",
        steps=["Step A"],
        expected_result="Success",
    )
    tc2 = TestCase(
        tc_id="TC-002",
        title="Login Invalid",
        requirement_ref="REQ-1",
        steps=["Step B"],
        expected_result="Failure",
    )

    coll_a = TestCaseCollection(version=1, testcases=[tc1, tc2])
    coll_b = TestCaseCollection(version=1, testcases=[tc2, tc1])  # Reversed list order

    # Canonical hashing must sort by tc_id and yield identical hash
    hash_a = coll_a.compute_sha256_hash()
    hash_b = coll_b.compute_sha256_hash()
    assert hash_a == hash_b
    assert len(hash_a) == 64


def test_hash_changes_on_modification():
    tc1 = TestCase(
        tc_id="TC-001",
        title="Login Valid",
        requirement_ref="REQ-1",
        steps=["Step A"],
        expected_result="Success",
    )
    coll = TestCaseCollection(version=1, testcases=[tc1])
    orig_hash = coll.compute_sha256_hash()

    # Modifying step content must alter hash
    tc1_modified = tc1.model_copy(update={"steps": ["Step A modified"]})
    coll_modified = TestCaseCollection(version=1, testcases=[tc1_modified])
    new_hash = coll_modified.compute_sha256_hash()

    assert orig_hash != new_hash
