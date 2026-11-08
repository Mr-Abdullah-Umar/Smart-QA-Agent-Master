"""Unit tests for FailureClassifier, Appendix B RCA categories, and Gate 2 sign-offs."""

from qa_engine.execution.runner import TestCaseOutcome
from qa_engine.investigation.classifier import FailureClassifier
from qa_engine.investigation.evidence import EvidenceIndex
from qa_engine.investigation.schemas import FailureCategory


def test_classify_flaky_test(tmp_path):
    index = EvidenceIndex()
    index.register_inline_text(
        content="retry passed log",
        base_dir=tmp_path,
        filename="retry.log",
        category="console_log",
        description="Retry execution log",
    )

    classifier = FailureClassifier(evidence_index=index)
    outcome = TestCaseOutcome(
        tc_id="TC-004",
        status="flaky",
        duration_seconds=3.2,
    )

    report = classifier.investigate(outcome)

    assert report.category == FailureCategory.FLAKY
    assert report.confidence >= 0.90
    assert len(report.facts) > 0
    assert report.facts[0].evidence_id == "EV-001"
    assert not report.requires_human_signoff


def test_classify_environment_failure(tmp_path):
    index = EvidenceIndex()
    index.register_inline_text(
        content="HTTP 500 server stack",
        base_dir=tmp_path,
        filename="server_error.log",
        category="network_log",
        description="500 internal server error response",
    )

    classifier = FailureClassifier(evidence_index=index)
    outcome = TestCaseOutcome(
        tc_id="TC-002",
        status="failed",
        error_message="Request failed with status code 500 Internal Server Error",
        stack_trace="APIClient.post -> 500 Internal Server Error",
    )

    report = classifier.investigate(outcome)

    assert report.category == FailureCategory.ENVIRONMENT_FAILURE
    assert len(report.facts) > 0
    assert report.facts[0].evidence_id == "EV-001"
    assert not report.requires_human_signoff


def test_classify_assertion_defect_and_gate_2_signoff(tmp_path):
    index = EvidenceIndex()
    index.register_inline_text(
        content="AssertionError: Expected 'Welcome' but got 'Error 404'",
        base_dir=tmp_path,
        filename="error.log",
        category="error",
        description="Assertion mismatch",
    )

    classifier = FailureClassifier(evidence_index=index)
    outcome = TestCaseOutcome(
        tc_id="TC-001",
        status="failed",
        error_message="AssertionError: Expected 'Welcome' but got 'Error 404'",
        stack_trace="Traceback: assert 'Welcome' in page_text\nAssertionError",
    )

    report = classifier.investigate(outcome)

    assert report.category == FailureCategory.PRODUCT_DEFECT
    # Gate 2 requirement must be enforced
    assert report.requires_human_signoff is True
    assert report.gate_2_signed_off is False
    assert report.signed_off_by is None

    # Sign off Gate 2 defect
    success = classifier.sign_off_defect(
        failure_id=report.failure_id,
        approver="lead_engineer@example.com",
        notes="Verified bug with backend team. Ticket PROD-1234 created.",
    )

    assert success is True
    assert report.gate_2_signed_off is True
    assert report.signed_off_by == "lead_engineer@example.com"
    assert report.signoff_notes is not None


def test_classify_timeout_automation_issue(tmp_path):
    index = EvidenceIndex()
    index.register_inline_text(
        content="Timeout waiting for locator",
        base_dir=tmp_path,
        filename="timeout.log",
        category="error",
        description="Timeout log",
    )

    classifier = FailureClassifier(evidence_index=index)
    outcome = TestCaseOutcome(
        tc_id="TC-003",
        status="failed",
        error_message="waiting for locator('button#submit') to be visible",
        stack_trace="playwright._impl._errors.TimeoutError: Timeout 30000ms exceeded",
    )

    report = classifier.investigate(outcome)

    assert report.category == FailureCategory.AUTOMATION_ISSUE
    assert not report.requires_human_signoff

