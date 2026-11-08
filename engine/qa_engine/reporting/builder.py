"""Multi-format Report Builder.

Implements Section 8.12 specifications:
- Generates reports in 4 formats:
  1. Self-contained HTML with Jinja2 autoescape and zero JavaScript.
  2. Markdown report for Git and issue tracker integration.
  3. Machine-readable JSON summary (`report.json`).
  4. Standard JUnit XML.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from xml.sax.saxutils import escape as xml_escape
from xml.sax.saxutils import quoteattr

from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, Field

from qa_engine.browser.extended_checks import ExtendedPageCheckResult
from qa_engine.execution.runner import ExecutionSummary
from qa_engine.generation.testcases import TestCaseCollection
from qa_engine.investigation.schemas import InvestigationReport
from qa_engine.orchestrator.run_store import RunStore


class RenderedTestOutcome(BaseModel):
    tc_id: str
    title: str = ""
    priority: str = "P1"
    category: str = "functional"
    ac_ref: str = ""
    status: str
    duration_seconds: float = 0.0
    error_message: Optional[str] = None


class ReportPayload(BaseModel):
    run_id: str
    generated_at: str
    target_url: str
    module: str = ""
    run_type: str = "initial"
    environment: str = ""
    triggered_by: str = ""
    gate_1_hash: Optional[str] = None
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    flaky: int = 0
    blocked: int = 0
    skipped: int = 0
    pass_rate: float = 0.0
    duration_seconds: float = 0.0
    test_outcomes: List[RenderedTestOutcome] = Field(default_factory=list)
    investigations: List[InvestigationReport] = Field(default_factory=list)
    extended_checks: Optional[ExtendedPageCheckResult] = None
    audit_count: int = 0
    audit_hash_head: str = ""


class ReportBuilder:
    """Builds HTML, Markdown, JSON, and JUnit XML test reports."""

    def __init__(self, templates_dir: Optional[Path] = None):
        if not templates_dir:
            templates_dir = Path(__file__).parent / "templates"
        self.templates_dir = templates_dir
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=True,
        )

    def prepare_payload(
        self,
        run_id: str,
        target_url: str,
        summary: ExecutionSummary,
        test_collection: Optional[TestCaseCollection] = None,
        investigations: Optional[List[InvestigationReport]] = None,
        extended_checks: Optional[ExtendedPageCheckResult] = None,
        gate_1_hash: Optional[str] = None,
        audit_count: int = 0,
        audit_hash_head: str = "",
        module: str = "",
        run_type: str = "initial",
        environment: str = "",
        triggered_by: str = "",
    ) -> ReportPayload:
        """Collate and normalize execution data into structured report payload."""
        # Map TC-ID to title and metadata
        tc_map = {}
        if test_collection:
            for tc in test_collection.testcases:
                tc_map[tc.tc_id.upper()] = tc

        rendered_outcomes: List[RenderedTestOutcome] = []
        for outcome in summary.outcomes:
            tc_meta = tc_map.get(outcome.tc_id.upper())
            rendered_outcomes.append(
                RenderedTestOutcome(
                    tc_id=outcome.tc_id,
                    title=tc_meta.title if tc_meta else f"Test {outcome.tc_id}",
                    priority=tc_meta.priority.value if tc_meta else "P1",
                    category=tc_meta.category.value if tc_meta else "functional",
                    ac_ref=(tc_meta.ac_ref or "") if tc_meta else "",
                    status=outcome.status.upper(),
                    duration_seconds=outcome.duration_seconds,
                    error_message=outcome.error_message,
                )
            )

        pass_rate = (
            (summary.passed / summary.total_tests * 100.0) if summary.total_tests > 0 else 0.0
        )

        return ReportPayload(
            run_id=run_id,
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            target_url=target_url,
            module=module,
            run_type=run_type,
            environment=environment,
            triggered_by=triggered_by,
            gate_1_hash=gate_1_hash,
            total_tests=summary.total_tests,
            passed=summary.passed,
            failed=summary.failed,
            flaky=summary.flaky,
            blocked=summary.blocked,
            skipped=summary.skipped,
            pass_rate=pass_rate,
            duration_seconds=summary.duration_seconds,
            test_outcomes=rendered_outcomes,
            investigations=investigations or [],
            extended_checks=extended_checks,
            audit_count=audit_count,
            audit_hash_head=audit_hash_head,
        )

    def generate_html(self, payload: ReportPayload) -> str:
        """Render self-contained HTML report with strict zero-JS invariant."""
        template = self.jinja_env.get_template("report.html.jinja2")
        html_out = template.render(payload.model_dump())

        # Enforce zero-JS constraint: reject or strip any <script> tag
        if "<script" in html_out.lower():
            raise ValueError("Security invariant violation: HTML report must not contain scripts.")

        return html_out

    def generate_markdown(self, payload: ReportPayload) -> str:
        """Render Markdown report."""
        template = self.jinja_env.get_template("report.md.jinja2")
        return template.render(payload.model_dump())

    def generate_json(self, payload: ReportPayload) -> str:
        """Render canonical JSON report."""
        return payload.model_dump_json(indent=2)

    def generate_junit_xml(self, payload: ReportPayload) -> str:
        """Generate standard JUnit XML representation."""
        lines = [
            '<?xml version="1.0" encoding="utf-8"?>',
            f'<testsuites time="{payload.duration_seconds:.2f}">',
            f'  <testsuite name="QA_Harness_Suite" tests="{payload.total_tests}" '
            f'failures="{payload.failed}" errors="0" '
            f'skipped="{payload.skipped + payload.blocked}" '
            f'time="{payload.duration_seconds:.2f}">',
        ]

        for tc in payload.test_outcomes:
            lines.append(
                f"    <testcase classname={quoteattr(payload.module or 'test_suite')} "
                f'name={quoteattr(tc.tc_id)} time="{tc.duration_seconds:.2f}">'
            )
            if tc.status == "FAILED":
                err_msg = tc.error_message or "Test failed"
                lines.append(
                    f"      <failure message={quoteattr(err_msg)}>{xml_escape(err_msg)}</failure>"
                )
            elif tc.status in ("SKIPPED", "BLOCKED"):
                reason = tc.error_message or f"Test {tc.status.lower()}"
                lines.append(f"      <skipped message={quoteattr(reason)}/>")
            lines.append("    </testcase>")

        lines.append("  </testsuite>")
        lines.append("</testsuites>")
        return "\n".join(lines)

    def write_all_reports(self, payload: ReportPayload, store: RunStore) -> Dict[str, Path]:
        """Generate and save HTML, Markdown, JSON, and JUnit XML to run directory."""
        report_dir = store.run_dir / "report"
        report_dir.mkdir(parents=True, exist_ok=True)

        html_content = self.generate_html(payload)
        md_content = self.generate_markdown(payload)
        json_content = self.generate_json(payload)
        junit_content = self.generate_junit_xml(payload)

        html_path = report_dir / "report.html"
        md_path = report_dir / "report.md"
        json_path = report_dir / "report.json"
        junit_path = report_dir / "junit.xml"

        html_path.write_text(html_content, encoding="utf-8")
        md_path.write_text(md_content, encoding="utf-8")
        json_path.write_text(json_content, encoding="utf-8")
        junit_path.write_text(junit_content, encoding="utf-8")

        return {
            "html": html_path,
            "markdown": md_path,
            "json": json_path,
            "junit": junit_path,
        }
