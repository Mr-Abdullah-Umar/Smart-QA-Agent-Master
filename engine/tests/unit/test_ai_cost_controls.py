"""AI cost controls: usage metering, failure signatures, reuse, caching, and limits."""

import json

import pytest

from qa_engine.execution.runner import TestCaseOutcome
from qa_engine.investigation.classifier import FailureClassifier
from qa_engine.investigation.evidence import EvidenceIndex
from qa_engine.investigation.planner import (
    InvestigationCache,
    InvestigationPolicy,
    failure_signature,
    investigate_failures,
)
from qa_engine.investigation.schemas import FailureCategory
from qa_engine.llm.mock_provider import MockLLMProvider
from qa_engine.llm.provider import LLMResponse
from qa_engine.llm.usage import AIUsageLedger, MeteredLLM, UsageCounter

LOCATOR_TIMEOUT = (
    "TimeoutError: Locator.click: Timeout {ms}ms exceeded waiting for "
    "get_by_role('button', name='Save changes')"
)


def _analysis(category: str = "Automation issue") -> str:
    return json.dumps(
        {
            "failure_id": "x",
            "tc_id": "x",
            "category": category,
            "confidence": 0.8,
            "facts": [{"statement": "Button missing", "evidence_id": "EV-001"}],
            "hypotheses": [{"hypothesis": "Button renamed", "supporting_indicators": []}],
            "evidence_citations": ["EV-001"],
            "reproduction_steps": ["Open page"],
            "recommended_action": "Update the locator",
            "preventive_measure": "Use test ids",
        }
    )


def _index(tmp_path, tc_ids):
    index = EvidenceIndex()
    for tc in tc_ids:
        index.register_inline_text(
            content=f"{tc} failed",
            base_dir=tmp_path,
            filename=f"{tc}.log",
            category="console_log",
            description=f"Log of {tc}",
        )
    return index


def _failed(tc_id, message, status="failed"):
    return TestCaseOutcome(tc_id=tc_id, status=status, error_message=message, stack_trace="")


def _setup(tmp_path, tc_ids, reply=None):
    mock = MockLLMProvider(canned_response=reply or _analysis())
    counter = UsageCounter()
    ledger = AIUsageLedger(str(tmp_path))
    llm = MeteredLLM(mock, "investigation", counter=counter, ledger=ledger)
    classifier = FailureClassifier(_index(tmp_path, tc_ids), llm=llm)
    return mock, counter, ledger, classifier


async def _run(classifier, outcomes, policy, ledger, cache, run_id="run-1", **kw):
    return await investigate_failures(
        outcomes,
        classifier,
        policy,
        ledger,
        cache,
        slug=kw.get("slug", "login"),
        suite_hash=kw.get("suite_hash", "hash-v1"),
        origin=kw.get("origin", "https://app.test"),
        run_id=run_id,
        priorities=kw.get("priorities"),
    )


def test_signature_ignores_timings_but_keeps_values():
    a = _failed("TC-1", LOCATOR_TIMEOUT.format(ms=5000))
    b = _failed("TC-1", LOCATOR_TIMEOUT.format(ms=10000))
    assert failure_signature(a) == failure_signature(b)
    other = _failed("TC-1", LOCATOR_TIMEOUT.format(ms=5000).replace("Save", "Delete"))
    assert failure_signature(other) != failure_signature(a)
    three = _failed("TC-1", "Expected 3 rows in the orders table, got 0 after 2.5 s")
    five = _failed("TC-1", "Expected 5 rows in the orders table, got 0 after 1.1 s")
    assert failure_signature(three) != failure_signature(five)
    assert "#ms" in failure_signature(three)


def test_signature_falls_back_to_last_stack_line():
    outcome = TestCaseOutcome(
        tc_id="TC-1", status="failed", stack_trace="frame 1\nAssertionError: 42 != 43\n"
    )
    assert failure_signature(outcome) == "AssertionError: 42 != 43"


@pytest.mark.asyncio
async def test_same_error_in_one_run_uses_one_ai_call(tmp_path):
    mock, counter, ledger, classifier = _setup(tmp_path, ["TC-1", "TC-2", "TC-3"])
    outcomes = [_failed(t, LOCATOR_TIMEOUT.format(ms=5000)) for t in ("TC-1", "TC-2", "TC-3")]
    reports, stats = await _run(classifier, outcomes, InvestigationPolicy(), ledger, None)
    assert len(mock.recorded_messages) == 1
    assert stats == {"ai": 1, "reused": 2, "cached": 0, "rules": 0, "limited": 0}
    assert [r.analysis_source for r in reports] == ["ai", "reused", "reused"]
    assert {r.tc_id for r in reports} == {"TC-1", "TC-2", "TC-3"}
    assert len({r.failure_id for r in reports}) == 3
    # Reused analyses cite this run's evidence of their own test.
    ev_of = {i.description: i.evidence_id for i in classifier.evidence_index.items.values()}
    assert reports[2].evidence_citations == [ev_of["Log of TC-3"]]
    assert counter.calls["investigation"] == 1
    assert ledger.today("investigation") == 1


@pytest.mark.asyncio
async def test_retest_of_shared_failures_needs_no_ai(tmp_path):
    cache = InvestigationCache(str(tmp_path))
    outcomes = [_failed(t, LOCATOR_TIMEOUT.format(ms=5000)) for t in ("TC-1", "TC-2")]
    mock, _, ledger, classifier = _setup(tmp_path, ["TC-1", "TC-2"])
    _, stats = await _run(classifier, outcomes, InvestigationPolicy(), ledger, cache)
    assert stats["ai"] == 1 and stats["reused"] == 1

    mock, _, ledger, classifier = _setup(tmp_path, ["TC-1", "TC-2"])
    retest = [_failed(t, LOCATOR_TIMEOUT.format(ms=7000)) for t in ("TC-2", "TC-1")]
    reports, stats = await _run(classifier, retest, InvestigationPolicy(), ledger, cache, "run-2")
    assert len(mock.recorded_messages) == 0
    assert stats["cached"] == 2
    assert all(r.analysis_source == "cached" for r in reports)


@pytest.mark.asyncio
async def test_generic_errors_are_not_shared_between_tests(tmp_path):
    mock, _, ledger, classifier = _setup(tmp_path, ["TC-1", "TC-2"])
    outcomes = [_failed("TC-1", "assert False"), _failed("TC-2", "assert False")]
    _, stats = await _run(classifier, outcomes, InvestigationPolicy(), ledger, None)
    assert stats["ai"] == 2
    assert len(mock.recorded_messages) == 2


@pytest.mark.asyncio
async def test_cached_analysis_is_reused_only_for_same_suite_version_and_target(tmp_path):
    cache = InvestigationCache(str(tmp_path))
    outcome = _failed("TC-1", LOCATOR_TIMEOUT.format(ms=5000))

    mock, _, ledger, classifier = _setup(tmp_path, ["TC-1"])
    await _run(classifier, [outcome], InvestigationPolicy(), ledger, cache, run_id="run-1")
    assert len(mock.recorded_messages) == 1

    mock2, _, ledger2, classifier2 = _setup(tmp_path, ["TC-1"])
    reports, stats = await _run(
        classifier2, [outcome], InvestigationPolicy(), ledger2, cache, run_id="run-2"
    )
    assert len(mock2.recorded_messages) == 0
    assert stats["cached"] == 1
    assert reports[0].analysis_source == "cached"
    assert "run-1" in reports[0].analysis_note

    for changed in ({"suite_hash": "hash-v2"}, {"origin": "https://staging.app.test"}):
        mock3, _, ledger3, classifier3 = _setup(tmp_path, ["TC-1"])
        _, stats = await _run(
            classifier3, [outcome], InvestigationPolicy(), ledger3, cache, run_id="r3", **changed
        )
        assert stats["ai"] == 1, changed
        assert len(mock3.recorded_messages) == 1


@pytest.mark.asyncio
async def test_cache_can_be_disabled_and_expires(tmp_path):
    outcome = _failed("TC-1", LOCATOR_TIMEOUT.format(ms=5000))
    cache = InvestigationCache(str(tmp_path))
    _, _, ledger, classifier = _setup(tmp_path, ["TC-1"])
    await _run(classifier, [outcome], InvestigationPolicy(), ledger, cache)

    mock, _, ledger, classifier = _setup(tmp_path, ["TC-1"])
    _, stats = await _run(
        classifier, [outcome], InvestigationPolicy(reuse_cached=False), ledger, cache
    )
    assert stats["ai"] == 1

    expired = InvestigationCache(str(tmp_path), ttl_days=0)
    data = json.loads(expired.path.read_text(encoding="utf-8"))
    for entry in data.values():
        entry["created_at"] = "2000-01-01T00:00:00+00:00"
    expired.path.write_text(json.dumps(data), encoding="utf-8")
    mock, _, ledger, classifier = _setup(tmp_path, ["TC-1"])
    _, stats = await _run(classifier, [outcome], InvestigationPolicy(), ledger, expired)
    assert stats["ai"] == 1


@pytest.mark.asyncio
async def test_per_run_limit_falls_back_to_rules_by_priority(tmp_path):
    tcs = ["TC-1", "TC-2", "TC-3"]
    mock, _, ledger, classifier = _setup(tmp_path, tcs)
    outcomes = [_failed(t, f"Element {t} not found on the dashboard page") for t in tcs]
    reports, stats = await _run(
        classifier,
        outcomes,
        InvestigationPolicy(max_ai_per_run=1),
        ledger,
        None,
        priorities={"TC-1": "P3", "TC-2": "P1", "TC-3": "P2"},
    )
    assert len(mock.recorded_messages) == 1
    assert stats["ai"] == 1 and stats["limited"] == 2
    by_tc = {r.tc_id: r for r in reports}
    assert by_tc["TC-2"].analysis_source == "ai"  # highest priority got the AI call
    assert by_tc["TC-1"].analysis_source == "rules"
    assert "limit" in by_tc["TC-1"].analysis_note


@pytest.mark.asyncio
async def test_daily_limit_is_shared_across_runs(tmp_path):
    ledger = AIUsageLedger(str(tmp_path))
    for _ in range(3):
        ledger.add("investigation")
    mock, _, _, classifier = _setup(tmp_path, ["TC-1"])
    _, stats = await _run(
        classifier,
        [_failed("TC-1", "Element TC-1 not found on the dashboard page")],
        InvestigationPolicy(daily_ai_limit=3),
        ledger,
        None,
    )
    assert len(mock.recorded_messages) == 0
    assert stats["limited"] == 1


@pytest.mark.asyncio
async def test_rules_need_no_ai_and_product_defects_keep_gate_2(tmp_path):
    mock, _, ledger, classifier = _setup(
        tmp_path, ["TC-1", "TC-2", "TC-3"], _analysis("Product defect")
    )
    outcomes = [
        _failed("TC-1", "flaky once", status="flaky"),
        _failed("TC-2", "net::ERR_CONNECTION_REFUSED at https://app.test"),
        _failed("TC-3", "Expected heading 'Welcome back' but got 'Error' on the page"),
        _failed("TC-4", "Expected heading 'Welcome back' but got 'Error' on the page"),
    ]
    reports, stats = await _run(classifier, outcomes, InvestigationPolicy(), ledger, None)
    assert len(mock.recorded_messages) == 1
    assert stats == {"ai": 1, "reused": 1, "cached": 0, "rules": 2, "limited": 0}
    by_tc = {r.tc_id: r for r in reports}
    assert by_tc["TC-1"].category == FailureCategory.FLAKY
    assert by_tc["TC-2"].category == FailureCategory.ENVIRONMENT_FAILURE
    for tc in ("TC-3", "TC-4"):
        assert by_tc[tc].category == FailureCategory.PRODUCT_DEFECT
        assert by_tc[tc].requires_human_signoff is True
        assert by_tc[tc].gate_2_signed_off is False


@pytest.mark.asyncio
async def test_ai_disabled_or_failing_still_classifies(tmp_path):
    _, _, ledger, classifier = _setup(tmp_path, ["TC-1"])
    outcome = _failed("TC-1", "TimeoutError: waiting for locator get_by_label('Email')")
    reports, stats = await _run(
        classifier, [outcome], InvestigationPolicy(ai_enabled=False), ledger, None
    )
    assert stats["rules"] == 1 and reports[0].analysis_source == "rules"

    _, _, ledger, broken = _setup(tmp_path, ["TC-1"], reply="not json at all")
    cache = InvestigationCache(str(tmp_path / "other"))
    reports, stats = await _run(broken, [outcome], InvestigationPolicy(), ledger, cache)
    assert stats["rules"] == 1
    assert reports[0].analysis_source == "rules"
    assert "failed" in reports[0].analysis_note
    assert not cache.path.exists()  # failed analyses are never cached


@pytest.mark.asyncio
async def test_metered_llm_passes_purpose_and_counts(tmp_path):
    seen = []

    class Recorder(MockLLMProvider):
        async def chat_with_purpose(self, purpose, messages, tools=None, temperature=0.2):
            seen.append(purpose)
            return LLMResponse(content="abcd" * 10)

    ledger = AIUsageLedger(str(tmp_path))
    counter = UsageCounter()
    llm = MeteredLLM(Recorder(), "design", counter=counter, ledger=ledger)
    await llm.chat([{"role": "user", "content": "x" * 40}])
    assert seen == ["design"]
    usage = counter.to_dict()
    assert usage["calls"]["design"] == 1
    assert usage["approx_tokens"]["design"] == 20
    assert ledger.today("design") == 1
    assert ledger.summary()["today"]["design_tokens"] == 20


def test_ledger_survives_a_corrupt_file(tmp_path):
    ledger = AIUsageLedger(str(tmp_path))
    ledger.path.parent.mkdir(parents=True)
    ledger.path.write_text("{broken", encoding="utf-8")
    assert ledger.today() == 0
    ledger.add("investigation")
    assert ledger.today("investigation") == 1
