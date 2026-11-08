"""Security Penetration: SSRF and DNS Rebinding Defenses (Appendix E Checklist).

Verifies T5 controls:
- Loopback, private RFC 1918, link-local, cloud metadata, and protocol smuggling.
- Outbound request interception rejecting non-whitelisted destinations.
"""

import pytest

from qa_engine.security.ssrf import (
    is_domain_allowed,
    is_ip_allowed,
    validate_destination_url,
)

ALLOWED_DOMAINS = ["example.com", ".myapp.internal.corp"]


@pytest.mark.parametrize(
    "prohibited_ip",
    [
        "127.0.0.1",
        "127.0.0.2",
        "127.1.2.3",
        "0.0.0.0",  # noqa: S104 # nosec B104
        "10.0.0.1",
        "10.255.255.254",
        "172.16.0.1",
        "172.31.255.255",
        "192.168.0.1",
        "192.168.1.254",
        "169.254.169.254",  # AWS / Azure / OpenStack metadata
        "169.254.1.1",  # Link-local IPv4
        "100.64.0.1",  # Carrier-grade NAT
        "::1",  # IPv6 Loopback
        "fc00::1",  # Unique Local IPv6
        "fe80::1",  # Link-Local IPv6
    ],
)
def test_blocked_ip_ranges(prohibited_ip):
    """Verify that every prohibited IP is correctly identified and rejected."""
    assert not is_ip_allowed(prohibited_ip), f"Failed to block prohibited IP: {prohibited_ip}"


@pytest.mark.parametrize(
    "blocked_host",
    [
        "localhost",
        "127.0.0.1",
        "metadata.google.internal",
        "instance-data",
    ],
)
def test_explicitly_blocked_hostnames(blocked_host):
    """Verify that dangerous hostnames are never allowed even if attempted."""
    assert not is_domain_allowed(blocked_host, ["localhost", "metadata.google.internal"])


@pytest.mark.parametrize(
    "scheme_url",
    [
        "file:///etc/passwd",
        "file:///C:/Windows/System32/drivers/etc/hosts",
        "ftp://ftp.example.com/file.txt",
        "gopher://127.0.0.1:6379/_INFO",
        "dict://127.0.0.1:11211/stats",
        "javascript:alert(1)",
        "data:text/html,<h1>Hello</h1>",
    ],
)
def test_protocol_smuggling_rejection(scheme_url):
    """Verify non-HTTP/HTTPS schemes are blocked with zero exception."""
    safe, reason = validate_destination_url(scheme_url, ALLOWED_DOMAINS, resolve_dns=False)
    assert not safe
    assert "Prohibited scheme" in (reason or "")


@pytest.mark.parametrize(
    "forbidden_destination",
    [
        "http://127.0.0.1:8080/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/internal-dashboard",
        "http://192.168.1.1/router-settings",
        "https://evil-attacker.com/malicious",
        "http://metadata.google.internal/computeMetadata/v1/",
    ],
)
def test_destination_url_validation_rejection(forbidden_destination):
    """Verify that destination URL validator rejects internal IPs and unwhitelisted domains."""
    safe, reason = validate_destination_url(
        forbidden_destination, ALLOWED_DOMAINS, resolve_dns=False
    )
    assert not safe
    assert reason is not None


def test_whitelisted_domain_acceptance():
    """Verify that legitimate URLs in allowed_domains pass validation."""
    valid_urls = [
        "https://example.com/login",
        "https://example.com:8443/api/v1/users",
        "https://app.myapp.internal.corp/home",
    ]
    for url in valid_urls:
        safe, reason = validate_destination_url(url, ALLOWED_DOMAINS, resolve_dns=False)
        assert safe, f"Expected safe for {url}, got: {reason}"
