"""Environment targeting, suite archive, update metadata, and review reopening."""

import asyncio

import pytest

import qa_engine.main as engine_main
from qa_engine.main import QAEngineServer
from qa_engine.orchestrator.run_store import RunStore, ScopeModel
from qa_engine.orchestrator.state_machine import (
    OrchestrationStateMachine,
    Stage,
    StateTransitionError,
)
from qa_engine.orchestrator.suite_store import SuiteRecord, SuiteStore


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    """Policy checks without network access; private/loopback hosts are still rejected."""
    real = engine_main.validate_destination_url

    def fake(url, domains, resolve_dns=False):
        return real(url, domains, resolve_dns=False)

    monkeypatch.setattr(engine_main, "validate_destination_url", fake)


def _record(**extra):
    return SuiteRecord(
        slug="cart",
        module="Cart",
        start_url="https://shop.test/app/",
        allowed_domains=["shop.test", "cdn.shop.test"],
        environment="staging",
        **extra,
    )


def test_default_environment_keeps_scope_without_mapping():
    scope, mapping = QAEngineServer._resolve_target(_record(), None)
    assert scope.start_url == "https://shop.test/app/"
    assert scope.environment == "staging"
    assert scope.allowed_domains == ["shop.test", "cdn.shop.test"]
    assert mapping == {}


def test_named_environment_swaps_host_and_maps_origin():
    record = _record(environments={"uat": "https://uat.shop.test/app/"})
    scope, mapping = QAEngineServer._resolve_target(record, "uat")
    assert scope.start_url == "https://uat.shop.test/app/"
    assert scope.allowed_domains == ["uat.shop.test", "cdn.shop.test"]
    assert mapping == {"https://shop.test": "https://uat.shop.test"}


def test_new_environment_url_and_unknown_environment():
    scope, mapping = QAEngineServer._resolve_target(
        _record(), "prod", "https://www.shop.example/app/"
    )
    assert scope.environment == "prod"
    assert "www.shop.example" in scope.allowed_domains
    assert mapping == {"https://shop.test": "https://www.shop.example"}

    with pytest.raises(ValueError, match="no URL for environment 'qa'"):
        QAEngineServer._resolve_target(_record(), "qa")


def test_environment_urls_obey_network_policy():
    with pytest.raises(ValueError, match="network policy"):
        QAEngineServer._resolve_target(_record(), "local", "http://127.0.0.1:8080/")
    with pytest.raises(ValueError, match="https:// or http://"):
        QAEngineServer._resolve_target(_record(), "ftp", "ftp://shop.test/")


def test_archive_moves_suite_out_of_library(tmp_path):
    store = SuiteStore(tmp_path)
    store.save_record(_record())
    target = store.archive("cart", "octocat")
    assert not store.exists("cart")
    assert (target / "suite.json").exists()
    log = (target.parent / "archive-log.json").read_text(encoding="utf-8")
    assert '"by": "octocat"' in log
    with pytest.raises(FileNotFoundError):
        store.archive("cart", "octocat")


def test_suite_get_and_delete_handlers(tmp_path):
    store = SuiteStore(tmp_path)
    store.save_record(_record(requirement_text="Users manage a cart."))
    (store.suite_dir("cart") / "criteria.json").write_text(
        '[{"id": "AC-1", "text": "Add item"}, {"id": "AC-2", "text": "Remove item"}]',
        encoding="utf-8",
    )
    server = QAEngineServer()

    async def go():
        info = await server.handle_suite_get({"workspace_root": str(tmp_path), "slug": "cart"})
        assert info["acceptance_criteria"] == "Add item\nRemove item"
        assert info["requirement_text"] == "Users manage a cart."
        assert info["extra_domains"] == ["cdn.shop.test"]
        with pytest.raises(ValueError, match="approver"):
            await server.handle_suite_delete({"workspace_root": str(tmp_path), "slug": "cart"})
        result = await server.handle_suite_delete(
            {"workspace_root": str(tmp_path), "slug": "cart", "approver": "octocat"}
        )
        assert result["status"] == "archived"

    asyncio.run(go())
    assert not store.exists("cart")


def test_reopen_review_withdraws_gate_1(tmp_path):
    store = RunStore(workspace_root=tmp_path, run_id="run-reopen")
    sm = OrchestrationStateMachine(run_store=store)

    async def go():
        await sm.confirm_scope(
            ScopeModel(
                start_url="https://shop.test/",
                allowed_domains=["shop.test"],
                environment="staging",
                authorized_attestation=True,
            ),
            actor="octocat",
        )
        await sm.advance_to(Stage.STAGE_5_REVIEW_LOOP)
        with pytest.raises(StateTransitionError):
            await sm.reopen_review("octocat", "too early")
        await sm.approve_testcases(1, "octocat", "abc")
        await sm.advance_to(Stage.STAGE_7_DRY_RUN)
        await sm.reopen_review("octocat", "broken locator")
        assert sm.state.current_stage == Stage.STAGE_5_REVIEW_LOOP
        assert not sm.state.testcases_approved
        with pytest.raises(StateTransitionError):
            await sm.advance_to(Stage.STAGE_8_EXECUTION)

    asyncio.run(go())
    audit = (store.run_dir / "audit.jsonl").read_text(encoding="utf-8")
    assert "GATE_1_APPROVAL_WITHDRAWN" in audit
