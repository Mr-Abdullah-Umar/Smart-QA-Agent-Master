"""Unit tests for ScriptGenerator and AST compliance."""

from qa_engine.generation.scriptgen import ScriptGenerator
from qa_engine.generation.testcases import TestCase, TestCasePriority
from qa_engine.generation.validator import ScriptValidator
from qa_engine.orchestrator.run_store import RunStore


def test_script_generation_and_validation(tmp_path):
    store = RunStore(workspace_root=tmp_path, run_id="run-gen-001")

    tc1 = TestCase(
        tc_id="TC-NAV-001",
        title="Verify home navigation",
        requirement_ref="REQ-01",
        priority=TestCasePriority.P2,
        steps=["Navigate to home", "Verify header is visible"],
        expected_result="Header is displayed",
    )

    scripts = ScriptGenerator.write_scripts(store, [tc1], page_name="home")

    assert scripts["page"].exists()
    assert scripts["test"].exists()

    test_content = scripts["test"].read_text(encoding="utf-8")
    assert '@pytest.mark.tc("TC-NAV-001")' in test_content
    assert "def test_tc_nav_001" in test_content

    # Validate that generated code passes the AST Security Validator
    is_valid, errors = ScriptValidator.validate_code(test_content, approved_tc_ids={"TC-NAV-001"})
    assert is_valid is True, f"Validation errors: {errors}"
