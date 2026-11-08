"""Harness conftest: secret placeholders, scope-locked navigation, blocked tests, masking."""

from qa_engine.execution.runner import SECRET_MASK, PytestRunner
from qa_engine.orchestrator.run_store import RunStore

SECRET = "hunter2-very-secret"  # noqa: S105

TESTS = """
import pytest


@pytest.mark.tc("TC-FIX-001")
def test_secret_resolves(harness_text):
    value = harness_text("pw={{secret.login_password}} id={{unique}}")
    print("resolved:", value)
    assert value.startswith("pw=hunter2-very-secret id=")
    assert False, value


@pytest.mark.tc("TC-FIX-002")
def test_out_of_scope_navigation_fails(harness_url):
    assert harness_url("/path") == "https://shop.test/path"
    harness_url("https://evil.test/")


@pytest.mark.tc("TC-FIX-003")
def test_missing_secret_blocks(harness_text):
    harness_text("{{secret.NOT_CONFIGURED}}")
"""


def test_harness_fixtures_and_secret_masking(tmp_path):
    store = RunStore(workspace_root=tmp_path, run_id="run-fixtures")
    tests_dir = store.run_dir / "scripts" / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_fixtures.py").write_text(TESTS, encoding="utf-8")

    lines = []
    summary = PytestRunner(store).run_tests(
        test_dir=tests_dir,
        base_url="https://shop.test/",
        retries=0,
        timeout_seconds=120,
        allowed_domains=["shop.test"],
        secrets={"LOGIN_PASSWORD": SECRET},
        on_output=lines.append,
    )

    by_id = {o.tc_id: o for o in summary.outcomes}
    assert by_id["TC-FIX-001"].status == "failed"
    assert by_id["TC-FIX-002"].status == "failed"
    assert "outside the confirmed scope" in (by_id["TC-FIX-002"].error_message or "")
    assert by_id["TC-FIX-003"].status == "blocked"
    assert summary.blocked == 1

    log = (store.run_dir / "evidence" / "logs" / "pytest_output.log").read_text(encoding="utf-8")
    junit = (store.run_dir / "results" / "junit.xml").read_text(encoding="utf-8")
    for text in (log, junit, "\n".join(lines), by_id["TC-FIX-001"].error_message or ""):
        assert SECRET not in text
    assert SECRET_MASK in junit


ENV_TESTS = """
import pytest


@pytest.mark.tc("TC-ENV-001")
def test_suite_urls_move_to_the_environment(harness_url):
    assert harness_url("") == "https://uat.shop.test/app/"
    assert harness_url("/cart") == "https://uat.shop.test/cart"
    assert harness_url("https://shop.test/cart?x=1") == "https://uat.shop.test/cart?x=1"
    assert harness_url("https://cdn.shop.test/a.js") == "https://cdn.shop.test/a.js"


@pytest.mark.tc("TC-ENV-002")
def test_expected_urls_move_to_the_environment(harness_url):
    assert harness_url.match("shop.test") == "uat.shop.test"
    assert harness_url.match("shop.test/cart") == "uat.shop.test/cart"
    assert harness_url.match("https://shop.test/cart") == "https://uat.shop.test/cart"
    assert harness_url.match("/cart") == "/cart"
"""


def test_origin_map_retargets_navigation_and_url_assertions(tmp_path):
    store = RunStore(workspace_root=tmp_path, run_id="run-env")
    tests_dir = store.run_dir / "scripts" / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_env.py").write_text(ENV_TESTS, encoding="utf-8")

    summary = PytestRunner(store).run_tests(
        test_dir=tests_dir,
        base_url="https://uat.shop.test/app/",
        retries=0,
        timeout_seconds=120,
        allowed_domains=["uat.shop.test", "cdn.shop.test"],
        origin_map={"https://shop.test": "https://uat.shop.test"},
    )
    assert summary.total_tests == 2
    assert summary.passed == 2, [o.error_message for o in summary.outcomes]
