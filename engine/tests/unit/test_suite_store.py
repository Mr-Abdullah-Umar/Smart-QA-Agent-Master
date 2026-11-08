"""Suite library persistence, Gate 1 integrity re-verification, and retest bookkeeping."""

import pytest

from qa_engine.generation.actions import TestAction
from qa_engine.generation.scriptgen import ScriptGenerator
from qa_engine.generation.testcases import TestCase, TestCaseCollection
from qa_engine.orchestrator.suite_store import (
    SuiteIntegrityError,
    SuiteRecord,
    SuiteRunSummary,
    SuiteStore,
    slugify,
)


def _collection():
    return TestCaseCollection(
        testcases=[
            TestCase(
                tc_id=f"TC-CART-00{i}",
                title=f"Case {i}",
                requirement_ref="REQ-CART",
                steps=["Open"],
                expected_result="Shown",
                test_types=["regression"],
                actions=[
                    TestAction(action="goto", value=""),
                    TestAction(action="expect_title", value="Shop"),
                ],
            )
            for i in (1, 2)
        ]
    )


def _saved_store(tmp_path):
    store = SuiteStore(tmp_path)
    collection = _collection()
    scripts = tmp_path / "run" / "scripts"
    ScriptGenerator.write_scripts(scripts, collection.testcases, "Cart")
    record = SuiteRecord(
        slug=slugify("Cart"),
        module="Cart",
        start_url="https://shop.test/",
        allowed_domains=["shop.test"],
        environment="staging",
    )
    approval = store.save_version(record, collection, scripts, "octocat", "# Cart", [], [])
    return store, approval


def test_save_and_verify_suite(tmp_path):
    store, approval = _saved_store(tmp_path)
    assert approval.version == 1 and approval.approver == "octocat"
    record = store.load("cart")
    assert record.current_version == 1 and record.total_cases == 2
    assert record.test_types == ["regression"]
    assert store.verify_integrity("cart").sha256_hash == approval.sha256_hash

    tests_dir = store.materialize_scripts("cart", tmp_path / "rerun" / "scripts")
    assert (tests_dir / "test_cart.py").exists()


def test_tampered_script_is_refused(tmp_path):
    store, _ = _saved_store(tmp_path)
    test_file = store.suite_dir("cart") / "versions" / "v1" / "scripts" / "tests" / "test_cart.py"
    test_file.write_text(test_file.read_text(encoding="utf-8") + "\nimport os\n", encoding="utf-8")
    with pytest.raises(SuiteIntegrityError, match="Scripts"):
        store.verify_integrity("cart")


def test_tampered_testcases_are_refused(tmp_path):
    store, _ = _saved_store(tmp_path)
    cases = store.suite_dir("cart") / "versions" / "v1" / "testcases.json"
    cases.write_text(cases.read_text(encoding="utf-8").replace("Case 1", "Edited"), "utf-8")
    with pytest.raises(SuiteIntegrityError, match="Test cases"):
        store.verify_integrity("cart")


def test_record_run_tracks_latest_status_for_failed_only_retest(tmp_path):
    store, _ = _saved_store(tmp_path)
    store.record_run(
        "cart",
        SuiteRunSummary(run_id="r1", run_type="initial", total=2, passed=1, failed=1),
        {"TC-CART-001": "passed", "TC-CART-002": "failed"},
    )
    store.record_run(
        "cart",
        SuiteRunSummary(run_id="r2", run_type="retest-failed", total=1, passed=1),
        {"TC-CART-002": "passed", "TC-GONE-009": "failed"},
    )
    assert store.latest_results("cart") == {"TC-CART-001": "passed", "TC-CART-002": "passed"}
    assert [h.run_id for h in store.history("cart")] == ["r1", "r2"]
    assert store.load("cart").last_run.run_id == "r2"


def test_slug_cannot_escape_library(tmp_path):
    store = SuiteStore(tmp_path)
    assert store.suite_dir("../../etc").parent == store.root
