import asyncio

import pytest

from qa_engine.main import PYTEST_RESULT_LINE
from qa_engine.orchestrator.activity import ActivityReporter


def _reporter():
    events = []

    async def notify(method, params):
        assert method == "activity"
        events.append(params)

    return ActivityReporter(notify), events


def test_step_reports_start_update_and_done():
    reporter, events = _reporter()

    async def flow():
        async with reporter.step("think", "Designing", "From 3 criteria") as step:
            await step.update("halfway")
            step.done("5 case(s) drafted")

    asyncio.run(flow())
    assert [e["phase"] for e in events] == ["start", "update", "end"]
    assert events[0]["kind"] == "think" and events[0]["title"] == "Designing"
    assert events[2]["status"] == "done" and events[2]["detail"] == "5 case(s) drafted"
    assert events[2]["duration_ms"] >= 0
    assert len({e["id"] for e in events}) == 1


def test_step_marks_failure_and_reraises():
    reporter, events = _reporter()

    async def flow():
        async with reporter.step("browse", "Opening"):
            raise RuntimeError("net::ERR_CONNECTION_TIMED_OUT\nstack")

    with pytest.raises(RuntimeError):
        asyncio.run(flow())
    assert events[-1]["status"] == "failed"
    assert events[-1]["detail"] == "net::ERR_CONNECTION_TIMED_OUT"


def test_step_reports_cancellation():
    reporter, events = _reporter()

    async def flow():
        async with reporter.step("wait", "Waiting"):
            await asyncio.sleep(10)

    async def main():
        task = asyncio.create_task(flow())
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
    assert events[-1]["status"] == "cancelled"


def test_notify_errors_never_break_the_workflow():
    async def broken(method, params):
        raise ConnectionError("pipe closed")

    async def flow():
        async with ActivityReporter(broken).step("run", "Running") as step:
            step.done("ok")
        return "finished"

    assert asyncio.run(flow()) == "finished"


def test_unknown_kind_falls_back_to_think():
    reporter, events = _reporter()

    async def flow():
        async with reporter.step("dance", "Odd"):
            pass

    asyncio.run(flow())
    assert events[0]["kind"] == "think"


def test_pytest_result_line_parsing():
    match = PYTEST_RESULT_LINE.search(
        "scripts/test_login.py::test_tc_login_001 PASSED                [ 20%]"
    )
    assert match and match.groups() == ("test_tc_login_001", "PASSED")
    match = PYTEST_RESULT_LINE.search("scripts/test_login.py::test_tc_login_002[chromium] FAILED")
    assert match and match.groups() == ("test_tc_login_002", "FAILED")
    assert PYTEST_RESULT_LINE.search("E   assert 1 == 2") is None
