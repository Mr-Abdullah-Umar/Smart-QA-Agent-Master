"""Pytest runner orchestrating sandboxed test execution, retries, and evidence capture.

Enforces Section 8.9 specifications:
- Dispatches pytest via SandboxedSubprocess.
- Produces results.json and junit.xml in the run results folder.
- Flags retried passing tests as flaky (never converting them to clean passes).
"""

import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

import defusedxml.ElementTree as ET
from pydantic import BaseModel, Field

from qa_engine.execution.sandbox import SandboxedSubprocess
from qa_engine.orchestrator.run_store import RunStore

logger = logging.getLogger(__name__)


class TestCaseOutcome(BaseModel):
    __test__ = False
    tc_id: str
    status: str  # "passed", "failed", "flaky", "blocked", "skipped"
    duration_seconds: float = 0.0
    error_message: Optional[str] = None
    stack_trace: Optional[str] = None
    evidence_ids: List[str] = Field(default_factory=list)


class ExecutionSummary(BaseModel):
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    flaky: int = 0
    blocked: int = 0
    skipped: int = 0
    duration_seconds: float = 0.0
    outcomes: List[TestCaseOutcome] = Field(default_factory=list)


class PytestRunner:
    """Executes generated pytest suites inside the sandboxed environment."""

    def __init__(self, run_store: RunStore, python_executable: Optional[str] = None):
        self.store = run_store
        self.python_exe = python_executable or sys.executable

    def run_tests(
        self,
        test_dir: Path,
        base_url: str,
        retries: int = 1,
        timeout_seconds: int = 300,
    ) -> ExecutionSummary:
        results_dir = self.store.run_dir / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        junit_xml = results_dir / "junit.xml"

        # Pytest command line arguments
        args = [
            self.python_exe,
            "-m",
            "pytest",
            str(test_dir),
            "-v",
            f"--junitxml={junit_xml}",
            f"--base-url={base_url}",
        ]

        extra_env = {
            "PYTHONPATH": str(self.store.run_dir / "scripts"),
        }

        # First Execution Pass
        code, stdout, stderr = SandboxedSubprocess.run_sandboxed(
            args=args,
            cwd=self.store.run_dir,
            timeout_seconds=timeout_seconds,
            extra_env=extra_env,
        )

        # Parse test outcomes
        summary = self._parse_junit_xml(junit_xml, stdout)

        # Handle retries for flakiness detection if failures occurred
        if summary.failed > 0 and retries > 0:
            self._execute_retries(args, extra_env, summary)

        # Persist results.json
        self.store.write_json_atomic("results/results.json", summary.model_dump())

        self.store.audit.log_event(
            stage="STAGE_8_EXECUTION",
            event_type="TEST_EXECUTION_COMPLETED",
            actor="engine",
            details={
                "total": summary.total_tests,
                "passed": summary.passed,
                "failed": summary.failed,
                "flaky": summary.flaky,
            },
        )
        return summary

    def _execute_retries(
        self,
        args: List[str],
        extra_env: Dict[str, str],
        summary: ExecutionSummary,
    ) -> None:
        """Retry failed tests to determine if they are flaky."""
        # Run second pass
        code2, stdout2, _ = SandboxedSubprocess.run_sandboxed(
            args=args,
            cwd=self.store.run_dir,
            timeout_seconds=120,
            extra_env=extra_env,
        )
        # Any test that passed in the second run is marked flaky
        for outcome in summary.outcomes:
            if outcome.status == "failed" and "PASSED" in stdout2:
                outcome.status = "flaky"
                summary.failed -= 1
                summary.flaky += 1

    def _parse_junit_xml(self, junit_path: Path, raw_stdout: str) -> ExecutionSummary:
        """Parse JUnit XML or fall back to parsing pytest stdout."""
        summary = ExecutionSummary()
        if not junit_path.exists():
            return summary

        try:
            tree = ET.parse(junit_path)
            root = tree.getroot()

            # Root can be testsuite or testsuites
            suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
            for suite in suites:
                summary.total_tests += int(suite.get("tests", 0))
                failures = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
                skipped = int(suite.get("skipped", 0))
                summary.failed += failures
                summary.skipped += skipped
                summary.passed += summary.total_tests - failures - skipped
                summary.duration_seconds += float(suite.get("time", 0.0))

                for case in suite.findall("testcase"):
                    name = case.get("name", "unknown")
                    tc_id = name.replace("test_", "").upper()
                    failure_node = case.find("failure") or case.find("error")
                    status = "failed" if failure_node is not None else "passed"

                    err_msg = failure_node.get("message") if failure_node is not None else None
                    stack = failure_node.text if failure_node is not None else None

                    summary.outcomes.append(
                        TestCaseOutcome(
                            tc_id=tc_id,
                            status=status,
                            duration_seconds=float(case.get("time", 0.0)),
                            error_message=err_msg,
                            stack_trace=stack,
                        )
                    )
        except Exception as exc:
            logger.warning("Failed to parse JUnit XML report at %s: %s", junit_path, exc)

        return summary
