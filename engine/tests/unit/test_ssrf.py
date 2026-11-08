"""Unit tests for SSRF and network domain controls (T5 controls)."""

from qa_engine.security.ssrf import (
    is_domain_allowed,
    is_ip_allowed,
    validate_destination_url,
)


def test_ip_allowed_filters():
    # Public IPs must be permitted
    assert is_ip_allowed("8.8.8.8") is True
    assert is_ip_allowed("93.184.216.34") is True

    # Loopback must be blocked
    assert is_ip_allowed("127.0.0.1") is False
    assert is_ip_allowed("127.1.2.3") is False

    # RFC 1918 Private networks must be blocked
    assert is_ip_allowed("10.0.0.1") is False
    assert is_ip_allowed("172.16.0.1") is False
    assert is_ip_allowed("172.31.255.255") is False
    assert is_ip_allowed("192.168.1.100") is False

    # Cloud metadata / Link-local must be blocked
    assert is_ip_allowed("169.254.169.254") is False
    assert is_ip_allowed("169.254.1.1") is False

    # IPv6 loopback and ULA must be blocked
    assert is_ip_allowed("::1") is False
    assert is_ip_allowed("fc00::1") is False


def test_domain_allowlist_matching():
    allowed = ["example.com", "staging.shop.org", ".mysite.io"]

    # Exact match
    assert is_domain_allowed("example.com", allowed) is True
    assert is_domain_allowed("staging.shop.org", allowed) is True

    # Subdomain match
    assert is_domain_allowed("api.example.com", allowed) is True
    assert is_domain_allowed("sub.mysite.io", allowed) is True

    # Disallowed domains
    assert is_domain_allowed("evil.com", allowed) is False
    assert is_domain_allowed("notexample.com", allowed) is False

    # Blocked hostnames
    assert is_domain_allowed("localhost", allowed) is False
    assert is_domain_allowed("127.0.0.1", allowed) is False


def test_url_validation_schemes_and_ips():
    allowed = ["example.com"]

    # Valid HTTP/HTTPS
    is_safe, err = validate_destination_url("https://example.com/login", allowed, resolve_dns=False)
    assert is_safe is True
    assert err is None

    # Prohibited schemes
    is_safe, err = validate_destination_url("file:///etc/passwd", allowed, resolve_dns=False)
    assert is_safe is False
    assert "Prohibited scheme" in err

    is_safe, err = validate_destination_url("javascript:alert(1)", allowed, resolve_dns=False)
    assert is_safe is False
    assert "Prohibited scheme" in err

    # Direct private IP in URL
    is_safe, err = validate_destination_url(
        "http://169.254.169.254/latest/meta-data/", allowed, resolve_dns=False
    )
    assert is_safe is False
    assert "metadata IP" in err or "not in the approved" in err
