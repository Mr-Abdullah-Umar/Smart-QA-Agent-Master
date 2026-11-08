"""Unit tests for JUnit parsing, TC-ID traceability, and smoke test design/generation."""

from qa_engine.browser.snapshot import AriaSnapshotExtractor
from qa_engine.execution.runner import PytestRunner
from qa_engine.generation.auto_design import design_smoke_testcases
from qa_engine.generation.scriptgen import ScriptGenerator
from qa_engine.generation.validator import ScriptValidator
from qa_engine.orchestrator.run_store import RunStore

JUNIT_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="3" failures="1" errors="0" skipped="1" time="4.5">
    <testcase classname="tests.test_login" name="test_valid_login[chromium]" time="1.5">
      <properties><property name="tc_id" value="TC-LOGIN-001"/></properties>
    </testcase>
    <testcase classname="tests.test_login" name="test_tc_login_002[chromium]" time="2.0">
      <failure message="AssertionError: banner missing">trace text</failure>
    </testcase>
    <testcase classname="tests.test_login" name="test_skip_me" time="0.0">
      <skipped message="skip"/>
    </testcase>
  </testsuite>
</testsuites>
"""


def test_junit_failures_are_not_reported_as_passes(tmp_path):
    store = RunStore(workspace_root=tmp_path, run_id="run-parse-001")
    junit = tmp_path / "junit.xml"
    junit.write_text(JUNIT_XML, encoding="utf-8")

    summary = PytestRunner(store)._parse_junit_xml(junit)

    assert (summary.total_tests, summary.passed, summary.failed, summary.skipped) == (3, 1, 1, 1)
    by_id = {o.tc_id: o for o in summary.outcomes}
    assert by_id["TC-LOGIN-001"].status == "passed"
    assert by_id["TC-LOGIN-002"].status == "failed"
    assert by_id["TC-LOGIN-002"].error_message == "AssertionError: banner missing"
    assert by_id["SKIP-ME"].status == "skipped"


def test_smoke_design_generates_valid_assertive_scripts(tmp_path):
    aria = "\n".join(
        [
            '- heading "Login Page" [level=2]',
            '- textbox "Username"',
            '- textbox "Password"',
            '- button "Login"',
            '- link "Elemental Selenium"',
        ]
    )
    snapshot = AriaSnapshotExtractor.build_snapshot(aria, "https://example.com/login", "The App")
    collection = design_smoke_testcases(snapshot, module="Login Page")

    ids = [tc.tc_id for tc in collection.testcases]
    assert ids[:2] == ["TC-LOGIN-PAGE-001", "TC-LOGIN-PAGE-002"]
    kinds = [[a.action for a in tc.actions] for tc in collection.testcases]
    assert kinds[0] == ["goto", "expect_title"]
    assert kinds.count(["goto", "fill", "expect_value"]) == 2
    assert ["goto", "expect_visible"] in kinds
    assert all("smoke" in tc.test_types for tc in collection.testcases)

    store = RunStore(workspace_root=tmp_path, run_id="run-smoke-001")
    scripts = ScriptGenerator.write_scripts(
        store.run_dir / "scripts", collection.testcases, "Login Page"
    )
    code = scripts["test"].read_text(encoding="utf-8")

    assert scripts["test"].name == "test_login_page.py"
    assert 'expect(page).to_have_title(re.compile(re.escape("The App")))' in code
    assert 'page.get_by_role("button", name="Login", exact=True).first' in code
    assert 'page.goto(harness_url(""))' in code
    assert "@pytest.mark.smoke" in code
    ok, errors = ScriptValidator.validate_code(
        code, approved_tc_ids={tc.tc_id for tc in collection.testcases}
    )
    assert ok, errors
