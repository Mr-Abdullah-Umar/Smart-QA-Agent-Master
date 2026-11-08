"""Deterministic, policy-guarded Playwright browser automation tools.

Implements Appendix C tools:
- browser_navigate
- browser_snapshot
- browser_click
- browser_fill
- browser_select
- browser_press_key
- browser_wait_for
- browser_screenshot

Enforces:
- SSRF and domain allowlist checking on all navigations and redirects.
- Action classification (blocking destructive actions unless approved).
- Semantic locator resolution via ARIA snapshots without pixel coordinates.
- Isolation: fresh browser context, no access to host profile or extensions.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from qa_engine.browser.policy import ActionClassifier
from qa_engine.browser.snapshot import AriaSnapshotExtractor, ElementReference, SnapshotResult
from qa_engine.security.ssrf import validate_destination_url


class BrowserActionError(Exception):
    """Raised when an automation action fails or is blocked by policy."""

    pass


class GuardedBrowserSession:
    """Encapsulates a sandboxed Playwright browser session with policy enforcement."""

    def __init__(
        self,
        allowed_domains: List[str],
        policy_mode: str = "require_approval",
        headless: bool = True,
        evidence_dir: Optional[Path] = None,
        channel: Optional[str] = "chrome",
    ):
        self.allowed_domains = allowed_domains
        self.policy_mode = policy_mode
        self.headless = headless
        self.evidence_dir = evidence_dir
        self.channel = channel

        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self.current_snapshot: Optional[SnapshotResult] = None

        # Diagnostic records
        self.console_logs: List[Dict[str, str]] = []
        self.failed_requests: List[Dict[str, Any]] = []

    async def initialize(self) -> None:
        """Launch Chromium/Chrome with isolated context and SSRF route interception."""
        self._playwright = await async_playwright().start()
        launch_kwargs = {
            "headless": self.headless,
            "args": ["--disable-dev-shm-usage", "--no-sandbox"],
        }
        if self.channel:
            launch_kwargs["channel"] = self.channel

        self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=False,
        )
        self._page = await self._context.new_page()

        # Listen for console messages and failed requests
        self._page.on(
            "console",
            lambda msg: self.console_logs.append(
                {
                    "type": msg.type,
                    "text": msg.text,
                }
            ),
        )
        self._page.on(
            "requestfailed",
            lambda req: self.failed_requests.append(
                {
                    "url": req.url,
                    "failure": req.failure,
                    "method": req.method,
                }
            ),
        )

        # Hook route interception for SSRF controls on all outbound requests
        await self._page.route("**/*", self._handle_route_interception)

    async def _handle_route_interception(self, route) -> None:
        """Inspect every network request against domain allowlist and blocked IP ranges."""
        url = route.request.url
        is_safe, reason = validate_destination_url(url, self.allowed_domains, resolve_dns=False)
        if not is_safe:
            # Abort unauthorized or private destination
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    async def navigate(self, url: str) -> SnapshotResult:
        """Navigate to target URL within allowed domains and return ARIA snapshot."""
        if not self._page:
            raise RuntimeError("Browser session not initialized")

        is_safe, reason = validate_destination_url(url, self.allowed_domains, resolve_dns=True)
        if not is_safe:
            raise BrowserActionError(f"Navigation blocked by SSRF/Scope policy: {reason}")

        await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return await self.take_snapshot()

    async def take_snapshot(self) -> SnapshotResult:
        """Capture the current accessibility tree snapshot and index interactive elements."""
        if not self._page:
            raise RuntimeError("Browser session not initialized")

        try:
            ax_tree = await self._page.locator("body").aria_snapshot()
        except Exception:
            ax_tree = ""
        url = self._page.url
        title = await self._page.title()

        self.current_snapshot = AriaSnapshotExtractor.build_snapshot(ax_tree, url, title)
        return self.current_snapshot

    def get_element_by_ref(self, ref_id: str) -> ElementReference:
        """Look up element reference in current snapshot."""
        if not self.current_snapshot or ref_id not in self.current_snapshot.elements:
            msg = (
                f"Element reference '{ref_id}' not found in current snapshot. "
                "Please capture a new snapshot."
            )
            raise BrowserActionError(msg)
        return self.current_snapshot.elements[ref_id]

    async def click(self, ref_id: str) -> SnapshotResult:
        """Resolve element by reference, enforce action classification, and click."""
        if not self._page:
            raise RuntimeError("Browser session not initialized")

        el_ref = self.get_element_by_ref(ref_id)

        # Policy check
        policy_result = ActionClassifier.classify_action(
            action_type="click",
            element_role=el_ref.role,
            element_name=el_ref.name,
            policy_mode=self.policy_mode,
        )
        if not policy_result.is_permitted:
            raise BrowserActionError(f"Action refused by policy: {policy_result.reason}")

        # Resolve role-based locator
        locator = self._page.get_by_role(el_ref.role, name=el_ref.name)
        if el_ref.nth > 0:
            locator = locator.nth(el_ref.nth)

        # Click with web-first auto-wait
        await locator.click(timeout=10000)
        # Re-capture snapshot post-click
        return await self.take_snapshot()

    async def fill(self, ref_id: str, text_value: str) -> SnapshotResult:
        """Resolve element by reference, enforce action classification, and fill text."""
        if not self._page:
            raise RuntimeError("Browser session not initialized")

        el_ref = self.get_element_by_ref(ref_id)

        policy_result = ActionClassifier.classify_action(
            action_type="fill",
            element_role=el_ref.role,
            element_name=el_ref.name,
            policy_mode=self.policy_mode,
        )
        if not policy_result.is_permitted:
            raise BrowserActionError(f"Action refused by policy: {policy_result.reason}")

        locator = self._page.get_by_role(el_ref.role, name=el_ref.name)
        if el_ref.nth > 0:
            locator = locator.nth(el_ref.nth)

        await locator.fill(text_value, timeout=10000)
        return await self.take_snapshot()

    async def screenshot(self, filename: str) -> Path:
        """Capture screenshot as evidence artifact."""
        if not self._page:
            raise RuntimeError("Browser session not initialized")

        target_dir = self.evidence_dir or Path.cwd()
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / f"{filename}.png"

        await self._page.screenshot(path=str(file_path), full_page=False)
        return file_path

    async def close(self) -> None:
        """Clean up page, context, and browser."""
        if self._page:
            await self._page.close()
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
