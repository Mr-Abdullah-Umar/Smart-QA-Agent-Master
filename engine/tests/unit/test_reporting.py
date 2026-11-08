"""Unit tests for ReportBuilder, HTML zero-JS enforcement, Markdown, JSON, and JUnit XML."""

import defusedxml.ElementTree as ET

from qa_engine.execution.runner import ExecutionSummary, TestCaseOutcome
from qa_engine.generation.testcases import TestCase, TestCaseCollection
from qa_engine.investigation.schemas import FailureCategory, InvestigationFact, InvestigationReport
from qa_engine.orchestrator.run_store import RunStore
from qa_engine.reporting.builder import ReportBuilder


def test_report_builder_payload_preparation(tmp_path):
    builder = ReportBuilder()

    summary = ExecutionSummary(
        total_tests=2,
        passed=1,
        failed=1,
        flaky=0,
        skipped=0,
        duration_seconds=5.4,
        outcomes=[
            TestCaseOutcome(tc_id="TC-001", status="passed", duration_seconds=2.1),
            TestCaseOutcome(
                tc_id="TC-002",
                status="failed",
                duration_seconds=3.3,
                error_message="AssertionError",
            ),
        ],
    )

    collection = TestCaseCollection(
        testcases=[
            TestCase(
                tc_id="TC-001",
                title="Verify Login with valid credentials",
                requirement_ref="REQ-AUTH-01",
                category="Functional positive",
                priority="P1",
                steps=["Enter credentials", "Click submit"],
                expected_result="Redirected to dashboard",
            ),
            TestCase(
                tc_id="TC-002",
                title="Verify Password Reset Link",
                requirement_ref="REQ-AUTH-02",
                category="Functional positive",
                priority="P2",
                steps=["Click forgot password", "Submit email"],
                expected_result="Reset email sent",
            ),
        ]
    )

    payload = builder.prepare_payload(
        run_id="run-test-123",
        target_url="https://app.example.com",
        summary=summary,
        test_collection=collection,
        gate_1_hash="abcdef0123456789",
        audit_count=10,
        audit_hash_head="deadbeef12345678",
    )

    assert payload.run_id == "run-test-123"
    assert payload.total_tests == 2
    assert payload.passed == 1
    assert payload.failed == 1
    assert payload.pass_rate == 50.0
    assert len(payload.test_outcomes) == 2
    assert payload.test_outcomes[0].title == "Verify Login with valid credentials"


def test_report_builder_zero_js_html_generation(tmp_path):
    builder = ReportBuilder()
    summary = ExecutionSummary(
        total_tests=1,
        passed=1,
        duration_seconds=1.0,
        outcomes=[TestCaseOutcome(tc_id="TC-001", status="passed", duration_seconds=1.0)],
    )
    payload = builder.prepare_payload(
        run_id="run-001",
        target_url="https://example.com",
        summary=summary,
    )

    html_out = builder.generate_html(payload)

    # Invariant: Must contain no script tags
    assert "<script" not in html_out.lower()
    assert "</script>" not in html_out.lower()
    assert "AI QA Testing Harness - Execution Report" in html_out
    assert "TC-001" in html_out


def test_report_builder_zero_js_invariant_enforcement():
    builder = ReportBuilder()
    summary = ExecutionSummary(
        total_tests=1,
        passed=0,
        failed=1,
        outcomes=[
            TestCaseOutcome(
                tc_id="TC-001",
                status="failed",
                error_message="<script>alert('xss')</script>",
            )
        ],
    )
    payload = builder.prepare_payload(
        run_id="run-sec",
        target_url="https://example.com",
        summary=summary,
    )

    # Jinja2 autoescape escapes <script> into &lt;script&gt;
    html_out = builder.generate_html(payload)
    assert "<script" not in html_out.lower()
    assert "&lt;script&gt;" in html_out


def test_report_builder_markdown_generation():
    builder = ReportBuilder()
    summary = ExecutionSummary(
        total_tests=1,
        passed=1,
        duration_seconds=2.0,
        outcomes=[TestCaseOutcome(tc_id="TC-001", status="passed", duration_seconds=2.0)],
    )
    inv = InvestigationReport(
        failure_id="FAIL-001",
        tc_id="TC-001",
        category=FailureCategory.FLAKY,
        confidence=0.9,
        facts=[InvestigationFact(statement="Passed retry", evidence_id="EV-001")],
        recommended_action="Fix timeout",
        preventive_measure="Use locator wait",
    )
    payload = builder.prepare_payload(
        run_id="run-md",
        target_url="https://example.com",
        summary=summary,
        investigations=[inv],
    )

    md_out = builder.generate_markdown(payload)

    assert "# QA Harness Execution Report" in md_out
    assert "| `TC-001` |" in md_out
    assert "FAIL-001" in md_out
    assert "`[EV-001]`" in md_out


def test_report_builder_junit_xml_validation():
    builder = ReportBuilder()
    summary = ExecutionSummary(
        total_tests=2,
        passed=1,
        failed=1,
        duration_seconds=3.0,
        outcomes=[
            TestCaseOutcome(tc_id="TC-001", status="passed", duration_seconds=1.0),
            TestCaseOutcome(
                tc_id="TC-002",
                status="failed",
                duration_seconds=2.0,
                error_message="Selector not found",
            ),
        ],
    )
    payload = builder.prepare_payload(
        run_id="run-xml",
        target_url="https://example.com",
        summary=summary,
    )

    xml_out = builder.generate_junit_xml(payload)

    # Validate with defusedxml
    root = ET.fromstring(xml_out)
    assert root.tag == "testsuites"
    suite = root.find("testsuite")
    assert suite is not None
    assert suite.get("tests") == "2"
    assert suite.get("failures") == "1"


def test_write_all_reports(tmp_path):
    store = RunStore(workspace_root=str(tmp_path), run_id="run-reports")
    builder = ReportBuilder()

    summary = ExecutionSummary(
        total_tests=1,
        passed=1,
        duration_seconds=1.5,
        outcomes=[TestCaseOutcome(tc_id="TC-001", status="passed", duration_seconds=1.5)],
    )
    payload = builder.prepare_payload(
        run_id="run-reports",
        target_url="https://example.com",
        summary=summary,
    )

    created_paths = builder.write_all_reports(payload, store)

    assert created_paths["html"].exists()
    assert created_paths["markdown"].exists()
    assert created_paths["json"].exists()
    assert created_paths["junit"].exists()

    assert created_paths["html"].stat().st_size > 0
    assert created_paths["markdown"].stat().st_size > 0
    assert created_paths["json"].stat().st_size > 0
    assert created_paths["junit"].stat().st_size > 0
