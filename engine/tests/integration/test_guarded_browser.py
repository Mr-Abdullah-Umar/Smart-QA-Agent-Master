"""Integration test verifying GuardedBrowserSession with real headless Chromium.

Validates:
- ARIA snapshot generation from live DOM.
- Reference-based element interactions (fill, click).
- Destructive action policy blocking.
- SSRF navigation blocking for private/metadata IPs.
- Evidence screenshot capture.
"""

import pytest

from qa_engine.browser.tools import BrowserActionError, GuardedBrowserSession

DEMO_HTML = """
<!DOCTYPE html>
<html>
<head><title>Demo Store</title></head>
<body>
  <h1>Product Search</h1>
  <form onsubmit="return false;">
    <input type="text" aria-label="Search Products" id="query" />
    <button type="submit">Search</button>
  </form>
  <div>
    <button>Add to Cart</button>
    <button>Delete Order</button>
  </div>
</body>
</html>
"""


@pytest.mark.asyncio
async def test_guarded_browser_live_interactions(tmp_path):
    evidence_dir = tmp_path / "evidence" / "screenshots"
    session = GuardedBrowserSession(
        allowed_domains=["demo.store"],
        policy_mode="require_approval",
        headless=True,
        evidence_dir=evidence_dir,
    )

    try:
        await session.initialize()

        # Load live DOM content
        await session._page.set_content(DEMO_HTML)

        # 1. Take Snapshot
        snapshot = await session.take_snapshot()
        assert snapshot.title == "Demo Store"
        assert snapshot.total_interactive_elements == 4

        # Search Products input, Search button, Add to Cart button, Delete Order button
        assert "#1" in snapshot.elements
        assert snapshot.elements["#1"].role == "textbox"

        # 2. Fill text into Search input using reference #1
        snapshot2 = await session.fill("#1", "Mechanical Keyboard")
        assert snapshot2 is not None

        # 3. Click Search button using reference #2
        snapshot3 = await session.click("#2")
        assert snapshot3 is not None

        # 4. Attempt to click 'Delete Order' (#4) -> Must be blocked by policy
        delete_ref = None
        for ref_id, el in snapshot.elements.items():
            if "delete" in el.name.lower():
                delete_ref = ref_id
                break

        assert delete_ref is not None
        with pytest.raises(BrowserActionError, match="Action refused by policy"):
            await session.click(delete_ref)

        # 5. Capture screenshot
        shot_path = await session.screenshot("test_interaction")
        assert shot_path.exists()
        assert shot_path.stat().st_size > 0

        # 6. SSRF Blocking check: attempt navigation to cloud metadata
        with pytest.raises(BrowserActionError, match="Navigation blocked by SSRF"):
            await session.navigate("http://169.254.169.254/latest/meta-data/")

    finally:
        await session.close()
