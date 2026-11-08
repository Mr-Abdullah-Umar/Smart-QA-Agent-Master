"""Unit tests for semantic version diffing (TestCaseDiffEngine)."""

from qa_engine.generation.diff import TestCaseDiffEngine
from qa_engine.generation.testcases import TestCase, TestCaseCollection, TestCasePriority


def test_version_diff_detection():
    tc1 = TestCase(
        tc_id="TC-001",
        title="Original Case",
        requirement_ref="REQ-1",
        steps=["Step 1"],
        expected_result="Result 1",
        priority=TestCasePriority.P2,
    )
    tc2 = TestCase(
        tc_id="TC-002",
        title="Removed Case",
        requirement_ref="REQ-1",
        steps=["Step 2"],
        expected_result="Result 2",
    )

    v1 = TestCaseCollection(version=1, testcases=[tc1, tc2])

    # In v2: tc1 modified, tc2 removed, tc3 added
    tc1_updated = tc1.model_copy(
        update={"priority": TestCasePriority.P1, "priority_rationale": "Elevated blocker"}
    )
    tc3 = TestCase(
        tc_id="TC-003",
        title="Newly Added Case",
        requirement_ref="REQ-2",
        steps=["Step 3"],
        expected_result="Result 3",
    )

    v2 = TestCaseCollection(version=2, testcases=[tc1_updated, tc3])

    diff = TestCaseDiffEngine.compute_diff(v1, v2)

    assert diff.old_version == 1
    assert diff.new_version == 2
    assert len(diff.added_cases) == 1
    assert diff.added_cases[0].tc_id == "TC-003"
    assert len(diff.removed_cases) == 1
    assert diff.removed_cases[0].tc_id == "TC-002"
    assert len(diff.modified_cases) == 1
    assert diff.modified_cases[0].tc_id == "TC-001"
    assert diff.modified_cases[0].changes[0].field_name == "priority"
    assert diff.modified_cases[0].changes[0].old_value == TestCasePriority.P2
    assert diff.modified_cases[0].changes[0].new_value == TestCasePriority.P1
