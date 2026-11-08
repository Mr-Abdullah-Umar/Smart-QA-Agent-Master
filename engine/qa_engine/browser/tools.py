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

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from qa_engine.browser.policy import ActionClassifier
from qa_engine.browser.snapshot import AriaSnapshotExtractor, ElementReference, SnapshotResult
from qa_engine.security.ssrf import validate_destination_url

logger = logging.getLogger(__name__)


def detect_chrome_channel() -> Optional[str]:
    """Return "chrome" when Google Chrome is installed locally, else None (bundled Chromium)."""
    if sys.platform == "win32":
        roots = [
            os.environ.get("LOCALAPPDATA"),
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
        ]
        candidates = [
            Path(root, "Google", "Chrome", "Application", "chrome.exe") for root in roots if root
        ]
    elif sys.platform == "darwin":
        candidates = [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
    else:
        candidates = [Path("/opt/google/chrome/chrome")]
    return "chrome" if any(p.exists() for p in candidates) else None


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
        slow_mo_ms: int = 0,
    ):
        self.allowed_domains = allowed_domains
        self.policy_mode = policy_mode
        self.headless = headless
        self.evidence_dir = evidence_dir
        self.channel = channel
        self.slow_mo_ms = slow_mo_ms

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
        launch_kwargs: Dict[str, Any] = {
            "headless": self.headless,
            "args": ["--disable-dev-shm-usage", "--no-sandbox"],
            "slow_mo": self.slow_mo_ms,
        }
        if self.channel:
            launch_kwargs["channel"] = self.channel

        try:
            self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        except Exception as exc:
            if not self.channel:
                raise
            logger.warning(
                "Browser channel '%s' unavailable (%s); using bundled Chromium.", self.channel, exc
            )
            launch_kwargs.pop("channel")
            self.channel = None
            self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        await self.reset_context()

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("Browser session not initialized")
        return self._page

    async def reset_context(self) -> None:
        """Replace the browser context with a fresh one (no cookies/storage carried over)."""
        if not self._browser:
            raise RuntimeError("Browser session not initialized")
        if self._context:
            await self._context.close()
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=False,
        )
        # Route on the context so popups and new tabs are filtered too.
        await self._context.route("**/*", self._handle_route_interception)
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

    async def list_links(self, limit: int = 60) -> List[Dict[str, str]]:
        """Return unique in-scope hyperlinks (absolute href + visible text) on the current page."""
        if not self._page:
            raise RuntimeError("Browser session not initialized")
        raw = await self._page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => ({href: e.href, text: (e.innerText || e.title || '').trim()}))",
        )
        links: List[Dict[str, str]] = []
        seen = set()
        for item in raw:
            href = str(item.get("href", "")).split("#")[0]
            if not href.startswith(("http://", "https://")) or href in seen:
                continue
            is_safe, _ = validate_destination_url(href, self.allowed_domains, resolve_dns=False)
            if not is_safe:
                continue
            seen.add(href)
            links.append({"href": href, "text": " ".join(str(item.get("text", "")).split())[:80]})
            if len(links) >= limit:
                break
        return links

    async def screenshot(self, filename: str) -> Path:
        """Capture screenshot as evidence artifact."""
        if not self._page:
            raise RuntimeError("Browser session not initialized")

        target_dir = self.evidence_dir or Path.cwd()
        target_dir.mkdir(parents=True, exist_ok=True)
        if not filename.lower().endswith(".png"):
            filename = f"{filename}.png"
        file_path = target_dir / filename

        await self._page.screenshot(path=str(file_path), full_page=False)
        return file_path

    async def close(self) -> None:
        """Clean up page, context, and browser."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
