"""Stage 7 dry run: replay each approved action plan once before the real execution.

Every element-targeting step must resolve to an element on the page it runs against;
interactions (click, fill, select, ...) are performed so later steps reach later pages.
Assertions are not evaluated here - a dry run only proves the plan is executable, so
genuine product failures still surface in the real run and its investigation.

Problems are reported per case together with the accessibility snapshot of the page where
the step broke, so the AI designer can repair the locators in a reviewed revision.
"""

import secrets as token_source
import time
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Literal, Optional, Tuple
from urllib.parse import urljoin

from pydantic import BaseModel, Field

from qa_engine.browser.snapshot import AriaSnapshotExtractor, SnapshotResult
from qa_engine.browser.tools import BrowserActionError, GuardedBrowserSession
from qa_engine.generation.actions import (
    SECRET_NAME,
    TestAction,
    build_locator,
    describe_action,
    expand_placeholders,
)
from qa_engine.generation.testcases import TestCase, TestCaseCollection

IssueKind = Literal["not_found", "out_of_range", "action_failed", "navigation_blocked"]

# Assertions whose target may legitimately be absent from the page.
_ABSENCE_OK = {"expect_hidden", "expect_count"}
_INTERACTIONS = {"click", "fill", "select", "check", "uncheck", "hover", "press"}

Navigator = Callable[[str], Awaitable[None]]


class DryRunIssue(BaseModel):
    tc_id: str
    step: int
    action: str
    kind: IssueKind
    detail: str
    page_url: str = ""
    screenshot: Optional[str] = None


class DryRunCaseResult(BaseModel):
    tc_id: str
    title: str = ""
    status: Literal["ok", "issue", "blocked"]
    steps_checked: int = 0
    total_steps: int = 0
    issue: Optional[DryRunIssue] = None
    missing_secrets: List[str] = Field(default_factory=list)


class DryRunReport(BaseModel):
    cases: List[DryRunCaseResult] = Field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def issues(self) -> List[DryRunIssue]:
        return [c.issue for c in self.cases if c.issue]

    @property
    def blocked(self) -> List[DryRunCaseResult]:
        return [c for c in self.cases if c.status == "blocked"]

    def revision_comments(self) -> str:
        """Reviewer-style instructions for the AI designer to repair the broken steps."""
        lines = [
            "The dry run could not execute these steps on the live application. Repair ONLY "
            "the listed steps using locators that exist in the page snapshots provided "
            "(including the snapshots of the pages where the steps failed). Keep every other "
            "case, step, and tc_id unchanged."
        ]
        for issue in self.issues:
            lines.append(
                f"- {issue.tc_id} step {issue.step} ({issue.action}) on {issue.page_url}: "
                f"{issue.detail}"
            )
        return "\n".join(lines)


def _first_line(text: str, limit: int = 300) -> str:
    line = next((part.strip() for part in str(text).splitlines() if part.strip()), "")
    return line[:limit]


class DryRunner:
    """Replays action plans against a Playwright page (navigation is injected)."""

    def __init__(
        self,
        start_url: str,
        secrets: Optional[Dict[str, str]] = None,
        locator_wait_ms: int = 5000,
        action_timeout_ms: int = 10000,
    ):
        self.start_url = start_url
        self.secrets = {k.upper(): v for k, v in (secrets or {}).items()}
        self.locator_wait_ms = locator_wait_ms
        self.action_timeout_ms = action_timeout_ms
        self.unique = f"{int(time.time())}{token_source.token_hex(2)}"

    async def run_case(
        self, page, case: TestCase, navigate: Navigator
    ) -> Tuple[DryRunCaseResult, bool]:
        """Return the case result and whether the page should be captured for repair."""
        actions = list(case.actions)
        if not actions or actions[0].action != "goto":
            actions.insert(0, TestAction(action="goto", value=""))
        result = DryRunCaseResult(
            tc_id=case.tc_id, title=case.title, status="ok", total_steps=len(actions)
        )
        for index, action in enumerate(actions, start=1):
            outcome = await self._run_step(page, case.tc_id, index, action, navigate)
            if isinstance(outcome, list):
                result.status, result.missing_secrets = "blocked", outcome
                return result, False
            if outcome is not None:
                result.status, result.issue = "issue", outcome
                return result, outcome.kind != "navigation_blocked"
            result.steps_checked = index
        return result, False

    async def _run_step(
        self, page, tc_id: str, index: int, action: TestAction, navigate: Navigator
    ):
        label = describe_action(action)

        def issue(kind: IssueKind, detail: str) -> DryRunIssue:
            return DryRunIssue(
                tc_id=tc_id, step=index, action=label, kind=kind, detail=detail, page_url=page.url
            )

        if action.action == "goto":
            url = urljoin(self.start_url, action.value) if action.value else self.start_url
            try:
                await navigate(url)
            except BrowserActionError as exc:
                return issue("navigation_blocked", str(exc))
            except Exception as exc:  # noqa: BLE001 - reported, not raised
                return issue("action_failed", f"Navigation failed: {_first_line(exc)}")
            return None

        value = action.value or ""
        if action.action in ("fill", "select"):
            expanded = expand_placeholders(value, self.secrets, self.unique)
            if expanded is None:
                return sorted({n.upper() for n in SECRET_NAME.findall(value)} - set(self.secrets))
            value = expanded

        target = action.target
        if target is not None and action.action not in _ABSENCE_OK:
            problem = await self._check_presence(page, action)
            if problem:
                return issue(*problem)

        if action.action not in _INTERACTIONS:
            return None
        try:
            await self._interact(page, action, value)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            return issue("action_failed", _first_line(exc))
        return None

    async def _check_presence(self, page, action: TestAction) -> Optional[Tuple[IssueKind, str]]:
        target = action.target
        if target is None:
            return None
        try:
            await build_locator(page, target).wait_for(
                state="attached", timeout=self.locator_wait_ms
            )
            return None
        except Exception:  # noqa: BLE001 - absence is the finding
            all_matches = target.model_copy(update={"nth": None})
            count = await build_locator(page, all_matches, single=False).count()
        name = f"{target.role or target.by} '{target.value}'"
        if count and target.nth is not None:
            return (
                "out_of_range",
                f"Only {count} element(s) match {name}, but index {target.nth} was requested.",
            )
        return "not_found", f"No element matches {name} on this page."

    async def _interact(self, page, action: TestAction, value: str) -> None:
        timeout = self.action_timeout_ms
        a = action.action
        locator = build_locator(page, action.target) if action.target else None
        if a == "press" and locator is None:
            await page.keyboard.press(value)
        elif a == "press":
            await locator.press(value, timeout=timeout)
        elif a == "click":
            await locator.click(timeout=timeout)
        elif a == "fill":
            await locator.fill(value, timeout=timeout)
        elif a == "select":
            await locator.select_option(value, timeout=timeout)
        elif a == "check":
            await locator.check(timeout=timeout)
        elif a == "uncheck":
            await locator.uncheck(timeout=timeout)
        elif a == "hover":
            await locator.hover(timeout=timeout)
        if a in ("click", "press"):
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=timeout)
            except Exception:  # noqa: BLE001, S110 - no navigation happened
                pass


async def run_dry_run(
    collection: TestCaseCollection,
    start_url: str,
    allowed_domains: List[str],
    secrets: Optional[Dict[str, str]],
    headless: bool,
    channel: Optional[str],
    slowmo_ms: int,
    evidence_dir: Path,
    on_case: Optional[Callable[[DryRunCaseResult], Awaitable[None]]] = None,
) -> Tuple[DryRunReport, List[SnapshotResult]]:
    """Dry-run every case in a fresh, isolated browser context under the scope policy."""
    started = time.monotonic()
    runner = DryRunner(start_url, secrets)
    report = DryRunReport()
    failure_pages: List[SnapshotResult] = []
    browser = GuardedBrowserSession(
        allowed_domains=allowed_domains,
        headless=headless,
        evidence_dir=evidence_dir,
        channel=channel,
        slow_mo_ms=slowmo_ms,
    )

    async def navigate(url: str) -> None:
        await browser.navigate(url)

    try:
        await browser.initialize()
        for case in collection.testcases:
            await browser.reset_context()
            result, capture = await runner.run_case(browser.page, case, navigate)
            if capture and result.issue:
                shot = await browser.screenshot(f"dryrun_{case.tc_id}")
                result.issue.screenshot = str(shot)
                failure_pages.append(await _snapshot(browser.page))
            report.cases.append(result)
            if on_case:
                await on_case(result)
    finally:
        await browser.close()
    report.duration_seconds = round(time.monotonic() - started, 1)
    return report, failure_pages


async def _snapshot(page) -> SnapshotResult:
    try:
        tree = await page.locator("body").aria_snapshot()
    except Exception:  # noqa: BLE001 - empty snapshot is still useful context
        tree = ""
    return AriaSnapshotExtractor.build_snapshot(tree, page.url, await page.title())
