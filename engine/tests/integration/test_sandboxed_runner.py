"""Integration test running real pytest in sandboxed runner and parsing results."""

from qa_engine.execution.runner import PytestRunner
from qa_engine.generation.scriptgen import ScriptGenerator
from qa_engine.generation.testcases import TestCase
from qa_engine.orchestrator.run_store import RunStore


def test_sandboxed_pytest_runner_execution(tmp_path):
    store = RunStore(workspace_root=tmp_path, run_id="run-runner-e2e")

    # Generate a simple test case
    tc = TestCase(
        tc_id="TC-RUNNER-001",
        title="Sample verification",
        requirement_ref="REQ-01",
        steps=["Open sample", "Check body"],
        expected_result="Body is visible",
    )

    scripts = ScriptGenerator.write_scripts(store, [tc], page_name="sample")

    runner = PytestRunner(store)
    summary = runner.run_tests(
        test_dir=scripts["test"].parent,
        base_url="https://example.com",
        retries=0,
        timeout_seconds=60,
    )

    # Verify results
    assert (store.run_dir / "results" / "junit.xml").exists()
    assert (store.run_dir / "results" / "results.json").exists()
    assert summary.total_tests == 1
