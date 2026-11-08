"""Stage 7 dry run: locator presence, interactions, secrets, and repair instructions.

Runs against static HTML in a real headless Chromium; navigation is injected so no network
access (and no SSRF exception for local content) is needed.
"""

import asyncio

from playwright.async_api import async_playwright

from qa_engine.browser.tools import detect_chrome_channel
from qa_engine.execution.dry_run import DryRunner, DryRunReport
from qa_engine.generation.actions import ElementLocator, TestAction
from qa_engine.generation.testcases import TestCase

LOGIN = """
<html><head><title>Sign in</title></head><body>
  <label for="u">Username</label><input id="u" />
  <label for="p">Password</label><input id="p" type="password" />
  <button onclick="document.body.insertAdjacentHTML('beforeend', '<h1>Welcome</h1>')">
    Sign in
  </button>
</body></html>
"""


def _case(tc_id, actions):
    return TestCase(
        tc_id=tc_id,
        title=tc_id,
        requirement_ref="REQ-T",
        steps=["s"],
        expected_result="e",
        actions=actions,
    )


def _role(role, name, nth=None):
    return ElementLocator(by="role", role=role, value=name, nth=nth)


def _run(case, secrets=None):
    async def go():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, channel=detect_chrome_channel())
            page = await browser.new_page()
            visited = []

            async def navigate(url):
                visited.append(url)
                await page.set_content(LOGIN)

            runner = DryRunner("https://app.example/login", secrets, locator_wait_ms=500)
            try:
                return await runner.run_case(page, case, navigate), visited
            finally:
                await browser.close()

    return asyncio.run(go())


def test_executable_plan_passes_and_interacts():
    case = _case(
        "TC-T-001",
        [
            TestAction(action="goto", value=""),
            TestAction(
                action="fill",
                target=ElementLocator(by="label", value="Username"),
                value="user-{{unique}}",
            ),
            TestAction(
                action="fill",
                target=ElementLocator(by="label", value="Password"),
                value="{{secret.PASSWORD}}",
            ),
            TestAction(action="click", target=_role("button", "Sign in")),
            TestAction(action="expect_visible", target=_role("heading", "Welcome")),
        ],
    )
    (result, capture), visited = _run(case, {"password": "pw-value"})
    assert result.status == "ok", result.issue
    assert result.steps_checked == result.total_steps == 5
    assert capture is False
    assert visited == ["https://app.example/login"]


def test_missing_locator_is_reported_with_step_and_capture():
    case = _case(
        "TC-T-002",
        [
            TestAction(action="goto", value=""),
            TestAction(action="click", target=_role("button", "Log in now")),
            TestAction(action="expect_visible", target=_role("heading", "Welcome")),
        ],
    )
    (result, capture), _ = _run(case)
    assert result.status == "issue"
    assert result.issue.kind == "not_found"
    assert result.issue.step == 2
    assert "Log in now" in result.issue.detail
    assert capture is True


def test_nth_out_of_range_and_absence_assertions():
    out_of_range = _case(
        "TC-T-003",
        [TestAction(action="click", target=_role("button", "Sign in", nth=3))],
    )
    (result, _), _ = _run(out_of_range)
    assert result.issue.kind == "out_of_range"
    assert result.issue.step == 2  # implicit goto is step 1

    hidden_ok = _case(
        "TC-T-004",
        [
            TestAction(action="goto", value=""),
            TestAction(action="expect_hidden", target=_role("alert", "Error")),
            TestAction(action="expect_count", target=_role("dialog", "Popup"), value="0"),
        ],
    )
    (result, _), _ = _run(hidden_ok)
    assert result.status == "ok"


def test_missing_secret_blocks_instead_of_failing():
    case = _case(
        "TC-T-005",
        [
            TestAction(action="goto", value=""),
            TestAction(
                action="fill",
                target=ElementLocator(by="label", value="Password"),
                value="{{secret.ADMIN_PASSWORD}}",
            ),
        ],
    )
    (result, capture), _ = _run(case)
    assert result.status == "blocked"
    assert result.missing_secrets == ["ADMIN_PASSWORD"]
    assert capture is False


def test_revision_comments_list_only_broken_steps():
    report = DryRunReport.model_validate(
        {
            "cases": [
                {"tc_id": "TC-A-001", "status": "ok"},
                {
                    "tc_id": "TC-A-002",
                    "status": "issue",
                    "issue": {
                        "tc_id": "TC-A-002",
                        "step": 3,
                        "action": "click button 'Go'",
                        "kind": "not_found",
                        "detail": "No element matches button 'Go' on this page.",
                        "page_url": "https://app.example/home",
                    },
                },
            ]
        }
    )
    comments = report.revision_comments()
    assert "TC-A-002 step 3" in comments
    assert "TC-A-001" not in comments
    assert "Keep every other" in comments
    assert len(report.issues) == 1
