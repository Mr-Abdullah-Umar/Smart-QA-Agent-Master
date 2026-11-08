"""Unit tests for Standardized Test Case Schema (Appendix A)."""

from qa_engine.generation.testcases import (
    TestCase,
    TestCaseCategory,
    TestCaseCollection,
    TestCasePriority,
)


def test_testcase_schema_valid():
    tc = TestCase(
        tc_id="TC-LOGIN-001",
        title="Verify successful authentication with valid credentials",
        requirement_ref="REQ-AUTH-01",
        category=TestCaseCategory.FUNCTIONAL_POSITIVE,
        priority=TestCasePriority.P1,
        priority_rationale="Core blocker: users cannot access system without login",
        preconditions=["User account exists and is active"],
        test_data={"username": "{{VALID_USER}}", "password": "{{VALID_PASSWORD}}"},
        steps=[
            "Navigate to the Login page",
            "Enter valid username into Username field",
            "Enter valid password into Password field",
            "Select Sign In",
        ],
        expected_result="Dashboard displays with user avatar and welcome message",
        postconditions="User is logged out",
        automation_candidate=True,
    )

    assert tc.tc_id == "TC-LOGIN-001"
    assert tc.priority == TestCasePriority.P1
    assert len(tc.steps) == 4
    assert tc.test_data["username"] == "{{VALID_USER}}"


def test_testcase_collection_json():
    collection = TestCaseCollection(
        version=1,
        testcases=[
            TestCase(
                tc_id="TC-001",
                title="Case 1",
                requirement_ref="REQ-1",
                steps=["Step 1"],
                expected_result="Expected 1",
            ),
            TestCase(
                tc_id="TC-002",
                title="Case 2",
                requirement_ref="REQ-2",
                steps=["Step 1", "Step 2"],
                expected_result="Expected 2",
            ),
        ],
    )

    dumped = collection.model_dump_json()
    loaded = TestCaseCollection.model_validate_json(dumped)
    assert len(loaded.testcases) == 2
    assert loaded.version == 1
