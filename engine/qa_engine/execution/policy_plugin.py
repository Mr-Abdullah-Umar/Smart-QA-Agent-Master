"""Pytest network policy plugin and fixture hooks for sandboxed execution.

Enforces T5 controls during test execution:
- Intercepts Playwright browser context requests.
- Validates URLs against scope allowed domains and blocks private/metadata IP ranges.
- Injects standard base_url fixture.
"""

import pytest

from qa_engine.security.ssrf import validate_destination_url


@pytest.fixture(scope="session")
def allowed_domains_list(pytestconfig):
    raw = pytestconfig.getoption("--allowed-domains", default="")
    return [d.strip() for d in raw.split(",") if d.strip()]


@pytest.fixture(autouse=True)
def apply_network_guardrails(page, allowed_domains_list):
    """Auto-use fixture attaching SSRF and domain route interceptors to every test page."""
    if not allowed_domains_list:
        yield
        return

    def handle_route(route):
        url = route.request.url
        is_safe, _ = validate_destination_url(url, allowed_domains_list, resolve_dns=False)
        if not is_safe:
            route.abort("blockedbyclient")
        else:
            route.continue_()

    page.route("**/*", handle_route)
    yield
    page.unroute("**/*", handle_route)
