"""Server-Side Request Forgery (SSRF) and network domain policy controls.

Enforces T5 controls:
- Restricts all browser navigation and sub-resource loading to approved domains.
- Blocks requests to loopback (127.0.0.0/8, ::1), private RFC 1918 ranges (10.0.0.0/8,
  172.16.0.0/12, 192.168.0.0/16), link-local (169.254.0.0/16), and cloud metadata
  endpoints (169.254.169.254) at DNS resolution time to mitigate DNS rebinding.
"""

import ipaddress
import socket
from typing import List, Optional, Set, Tuple
from urllib.parse import urlparse


class SSRFSecurityError(Exception):
    """Raised when an outbound request targets a prohibited or internal network destination."""

    pass


# Prohibited CIDR ranges
BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),  # Current network (only valid as source)
    ipaddress.ip_network("127.0.0.0/8"),  # Loopback IPv4
    ipaddress.ip_network("10.0.0.0/8"),  # RFC 1918 Class A Private
    ipaddress.ip_network("172.16.0.0/12"),  # RFC 1918 Class B Private
    ipaddress.ip_network("192.168.0.0/16"),  # RFC 1918 Class C Private
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local / AWS / GCP / Azure metadata
    ipaddress.ip_network("100.64.0.0/10"),  # Shared address space / Carrier-grade NAT
    ipaddress.ip_network("192.0.0.0/24"),  # IETF Protocol Assignments
    ipaddress.ip_network("198.18.0.0/15"),  # Benchmarking
    ipaddress.ip_network("224.0.0.0/4"),  # Multicast
    ipaddress.ip_network("240.0.0.0/4"),  # Reserved
    ipaddress.ip_network("::1/128"),  # Loopback IPv6
    ipaddress.ip_network("fc00::/7"),  # Unique Local IPv6 (ULA)
    ipaddress.ip_network("fe80::/10"),  # Link-Local IPv6
]

# Explicitly blocked hostnames
BLOCKED_HOSTNAMES: Set[str] = {
    "localhost",
    "127.0.0.1",
    "metadata.google.internal",
    "instance-data",
}


def is_ip_allowed(ip_str: str) -> bool:
    """Verify that an IP address does not fall within any private, loopback, or metadata ranges."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False

    for net in BLOCKED_NETWORKS:
        if ip in net:
            return False

    return True


def is_domain_allowed(hostname: str, allowed_domains: List[str]) -> bool:
    """Verify that a hostname matches the explicit allowed_domains whitelist."""
    if not hostname:
        return False

    hostname = hostname.lower().strip()
    if hostname in BLOCKED_HOSTNAMES:
        return False

    for allowed in allowed_domains:
        allowed = allowed.lower().strip()
        if hostname == allowed:
            return True
        # Allow subdomains if allowed entry starts with a dot or matches exact domain suffix
        if allowed.startswith(".") and hostname.endswith(allowed):
            return True
        if hostname.endswith("." + allowed):
            return True

    return False


def validate_destination_url(
    url: str,
    allowed_domains: List[str],
    resolve_dns: bool = True,
) -> Tuple[bool, Optional[str]]:
    """Validate a URL against scheme, allowed domains, and resolved IP ranges.

    Returns (True, None) if safe, or (False, error_reason) if blocked.
    """
    if not url:
        return False, "Empty URL"

    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, f"Malformed URL: {e}"

    if parsed.scheme.lower() not in ("http", "https"):
        return False, f"Prohibited scheme: '{parsed.scheme}'. Only http and https are permitted."

    hostname = parsed.hostname
    if not hostname:
        return False, "Missing hostname in URL"

    hostname = hostname.lower()

    # Check direct IP addresses in URL
    try:
        ip = ipaddress.ip_address(hostname)
        if not is_ip_allowed(str(ip)):
            return False, f"Direct access to private or metadata IP '{hostname}' is blocked."
    except ValueError:
        pass  # Hostname is a domain name, not a literal IP

    # Validate hostname against allowed domains
    if not is_domain_allowed(hostname, allowed_domains):
        return False, f"Domain '{hostname}' is not in the approved allowed_domains list."

    # DNS Resolution check (mitigates DNS rebinding to 127.0.0.1 or 169.254.169.254)
    if resolve_dns:
        try:
            addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
            resolved_ips = {item[4][0] for item in addr_info}
            for ip_addr in resolved_ips:
                if not is_ip_allowed(ip_addr):
                    return False, f"Domain '{hostname}' resolved to prohibited IP '{ip_addr}'."
        except socket.gaierror as e:
            return False, f"DNS resolution failed for '{hostname}': {e}"

    return True, None
