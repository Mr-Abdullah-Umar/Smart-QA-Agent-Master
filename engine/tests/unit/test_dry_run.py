"""Unit tests for DryRunStabilizer invariant: assertions are never auto-repaired."""

from qa_engine.execution.dry_run import DryRunStabilizer
from qa_engine.execution.runner import ExecutionSummary, PytestRunner, TestCaseOutcome
from qa_engine.orchestrator.run_store import RunStore


class MockRunner(PytestRunner):
    def __init__(self, outcomes):
        self.outcomes = outcomes

    def run_tests(self, test_dir, base_url, retries=0, timeout_seconds=120):
        failed_count = sum(1 for o in self.outcomes if o.status == "failed")
        return ExecutionSummary(
            total_tests=len(self.outcomes),
            passed=len(self.outcomes) - failed_count,
            failed=failed_count,
            outcomes=self.outcomes,
        )


def test_dry_run_assertion_invariant(tmp_path):
    store = RunStore(workspace_root=tmp_path, run_id="run-dry-001")

    # Simulate 1 locator timeout failure, and 1 real assertion failure
    mock_outcomes = [
        TestCaseOutcome(
            tc_id="TC-001",
            status="failed",
            error_message="TimeoutError: waiting for locator('button.submit')",
        ),
        TestCaseOutcome(
            tc_id="TC-002",
            status="failed",
            error_message="AssertionError: assert 'Dashboard' == 'Welcome'",
        ),
    ]

    mock_runner = MockRunner(mock_outcomes)
    stabilizer = DryRunStabilizer(store, mock_runner)

    stabilizer.execute_dry_run(test_dir=tmp_path, base_url="https://test.local")

    # Invariant checks:
    # 1. Timing issue was repaired
    # 2. AssertionError was BLOCKED and NOT auto-repaired!
    assert "TC-002" in stabilizer.log.blocked_test_cases
    assert stabilizer.log.total_repairs_attempted == 1
    assert stabilizer.log.successful_repairs == 1

    # Check repair-log.json was written
    assert (store.run_dir / "repair-log.json").exists()

