"""Unit tests for extended non-functional checks (security headers, performance, accessibility)."""

from qa_engine.browser.extended_checks import (
    AccessibilityViolation,
    ExtendedChecksCollector,
    PerformanceTiming,
)


def test_security_headers_audit():
    # Incomplete headers
    headers_insecure = {
        "Server": "nginx",
        "Content-Type": "text/html; charset=UTF-8",
    }
    result = ExtendedChecksCollector.analyze_security_headers(headers_insecure)

    assert not result.has_csp
    assert not result.has_hsts
    assert not result.has_x_content_type_options
    assert not result.has_x_frame_options
    assert "Content-Security-Policy" in result.missing_recommended_headers
    assert "Strict-Transport-Security" in result.missing_recommended_headers

    # Secure headers
    headers_secure = {
        "content-security-policy": "default-src 'self'",
        "strict-transport-security": "max-age=31536000; includeSubDomains",
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "referrer-policy": "strict-origin-when-cross-origin",
    }
    secure_result = ExtendedChecksCollector.analyze_security_headers(headers_secure)

    assert secure_result.has_csp
    assert secure_result.has_hsts
    assert secure_result.has_x_content_type_options
    assert secure_result.has_x_frame_options
    assert secure_result.has_referrer_policy
    assert len(secure_result.missing_recommended_headers) == 0


def test_performance_timing_model():
    timing = PerformanceTiming(
        dom_content_loaded_ms=245.5,
        load_event_ms=612.0,
        response_duration_ms=45.2,
    )
    assert timing.dom_content_loaded_ms == 245.5
    assert timing.load_event_ms == 612.0


def test_accessibility_violation_model():
    violation = AccessibilityViolation(
        rule_id="image-alt",
        impact="critical",
        description="Image missing alt attribute",
        help_text="Provide descriptive alt attribute",
        selector="img#logo",
    )
    assert violation.rule_id == "image-alt"
    assert violation.impact == "critical"
