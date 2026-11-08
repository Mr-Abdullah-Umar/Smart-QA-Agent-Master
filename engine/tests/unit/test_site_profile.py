"""Unit tests for SiteProfile aggregation."""

from qa_engine.browser.profile import SiteProfile
from qa_engine.browser.snapshot import AriaSnapshotExtractor


def test_site_profile_page_ingestion():
    profile = SiteProfile(
        start_url="https://staging.example.com",
        allowed_domains=["staging.example.com"],
    )

    mock_ax_tree = {
        "role": "WebArea",
        "name": "Checkout",
        "children": [
            {"role": "textbox", "name": "Shipping Address", "children": []},
            {"role": "combobox", "name": "Country", "children": []},
            {"role": "button", "name": "Place Order", "children": []},
        ],
    }

    snapshot = AriaSnapshotExtractor.build_snapshot(
        mock_ax_tree,
        url="https://staging.example.com/checkout",
        title="Checkout Page",
    )

    console_logs = [{"type": "warning", "text": "Form autocomplete disabled"}]
    failed_requests = [
        {"url": "https://staging.example.com/analytics", "failure": "net::ERR_BLOCKED"}
    ]

    page = profile.add_page(snapshot, console_logs=console_logs, failed_requests=failed_requests)

    assert len(profile.pages) == 1
    assert page.title == "Checkout Page"
    assert len(page.forms) == 1
    assert len(page.forms[0].fields) == 2  # textbox + combobox
    assert len(profile.console_errors) == 1
    assert len(profile.failed_requests) == 1
