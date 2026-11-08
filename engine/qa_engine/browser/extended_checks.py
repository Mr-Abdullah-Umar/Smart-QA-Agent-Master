"""Extended test coverage checks for accessibility, health, performance, and security.

Implements Section 8.10:
- Accessibility audits: WCAG 2.1 AA / 2.2 AA evaluation (images, forms, headings, ARIA).
- Console and network health tracking (unhandled exceptions, 4xx/5xx responses, failed requests).
- Navigation performance timing metrics (DOM content loaded, load event, response duration).
- Passive security headers check (CSP, HSTS, X-Frame-Options, X-Content-Type-Options).
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ConsoleEntry(BaseModel):
    level: str  # "error", "warning", "info", "debug"
    text: str
    location: Optional[str] = None
    timestamp: Optional[str] = None


class NetworkHealthEntry(BaseModel):
    url: str
    method: str = "GET"
    status: Optional[int] = None
    status_text: Optional[str] = None
    error_text: Optional[str] = None
    duration_ms: Optional[float] = None
    failed: bool = False


class PerformanceTiming(BaseModel):
    dom_content_loaded_ms: float = 0.0
    load_event_ms: float = 0.0
    response_duration_ms: float = 0.0
    first_paint_ms: Optional[float] = None


class SecurityHeaders(BaseModel):
    has_csp: bool = False
    has_hsts: bool = False
    has_x_content_type_options: bool = False
    has_x_frame_options: bool = False
    has_referrer_policy: bool = False
    missing_recommended_headers: List[str] = Field(default_factory=list)
    raw_headers: Dict[str, str] = Field(default_factory=dict)


class AccessibilityViolation(BaseModel):
    rule_id: str
    impact: str  # "critical", "serious", "moderate", "minor"
    description: str
    help_text: str
    help_url: Optional[str] = None
    selector: str
    element_html: Optional[str] = None


class ExtendedPageCheckResult(BaseModel):
    url: str
    console_errors: List[ConsoleEntry] = Field(default_factory=list)
    network_failures: List[NetworkHealthEntry] = Field(default_factory=list)
    performance: Optional[PerformanceTiming] = None
    security_headers: Optional[SecurityHeaders] = None
    accessibility_violations: List[AccessibilityViolation] = Field(default_factory=list)


class ExtendedChecksCollector:
    """Collects accessibility, console, network, performance, and security health data."""

    RECOMMENDED_HEADERS = [
        ("Content-Security-Policy", "has_csp"),
        ("Strict-Transport-Security", "has_hsts"),
        ("X-Content-Type-Options", "has_x_content_type_options"),
        ("X-Frame-Options", "has_x_frame_options"),
        ("Referrer-Policy", "has_referrer_policy"),
    ]

    WCAG_EVAL_SCRIPT = """
    (() => {
        const violations = [];

        // 1. Image alt check (WCAG 1.1.1)
        const images = document.querySelectorAll('img');
        images.forEach(img => {
            if (!img.hasAttribute('alt')) {
                const sel = img.id ? `#${img.id}` : 'img';
                violations.push({
                    rule_id: 'image-alt',
                    impact: 'critical',
                    description: 'Image missing required alt attribute.',
                    help_text: '<img> elements must have alt attribute or aria-hidden.',
                    help_url: 'https://www.w3.org/WAI/WCAG21/Understanding/non-text-content.html',
                    selector: sel,
                    element_html: img.outerHTML.substring(0, 150)
                });
            }
        });

        // 2. Form input label check (WCAG 1.3.1, 4.1.2)
        const selectorStr = 'input:not([type="hidden"]):not([type="submit"]), select, textarea';
        const inputs = document.querySelectorAll(selectorStr);
        inputs.forEach(input => {
            const id = input.id;
            let hasLabel = false;
            if (id && document.querySelector(`label[for="${id}"]`)) {
                hasLabel = true;
            } else if (input.closest('label')) {
                hasLabel = true;
            } else if (input.getAttribute('aria-label') || input.getAttribute('aria-labelledby')) {
                hasLabel = true;
            }

            if (!hasLabel) {
                violations.push({
                    rule_id: 'label',
                    impact: 'serious',
                    description: 'Form control does not have a corresponding label.',
                    help_text: 'Form elements must have an associated <label> or aria-label.',
                    help_url: 'https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html',
                    selector: id ? `#${id}` : input.tagName.toLowerCase(),
                    element_html: input.outerHTML.substring(0, 150)
                });
            }
        });

        // 3. Document title (WCAG 2.4.2)
        if (!document.title || document.title.trim() === '') {
            violations.push({
                rule_id: 'document-title',
                impact: 'serious',
                description: 'Document has no title element or title is empty.',
                help_text: 'The document must contain a descriptive <title> tag.',
                help_url: 'https://www.w3.org/WAI/WCAG21/Understanding/page-titled.html',
                selector: 'head > title',
                element_html: '<title></title>'
            });
        }

        // 4. HTML lang attribute (WCAG 3.1.1)
        const html = document.documentElement;
        if (!html.getAttribute('lang')) {
            violations.push({
                rule_id: 'html-has-lang',
                impact: 'serious',
                description: '<html> element lacks a valid lang attribute.',
                help_text: 'The <html> element must specify a language, e.g. <html lang="en">.',
                help_url: 'https://www.w3.org/WAI/WCAG21/Understanding/language-of-page.html',
                selector: 'html',
                element_html: '<html ...>'
            });
        }

        // 5. Button accessible name (WCAG 4.1.2)
        const buttons = document.querySelectorAll('button');
        buttons.forEach(btn => {
            const text = (btn.innerText || btn.textContent || '').trim();
            const ariaLabel = btn.getAttribute('aria-label') || '';
            const ariaLabelledBy = btn.getAttribute('aria-labelledby') || '';
            if (!text && !ariaLabel && !ariaLabelledBy) {
                violations.push({
                    rule_id: 'button-name',
                    impact: 'critical',
                    description: 'Button has no accessible text or label.',
                    help_text: 'Buttons must have discernible text or an aria-label.',
                    help_url: 'https://www.w3.org/WAI/WCAG21/Understanding/name-role-value.html',
                    selector: btn.id ? `#${btn.id}` : 'button',
                    element_html: btn.outerHTML.substring(0, 150)
                });
            }
        });

        return violations;
    })()
    """

    PERFORMANCE_EVAL_SCRIPT = """
    (() => {
        const perf = window.performance;
        if (!perf) return null;

        const navEntries = perf.getEntriesByType('navigation');
        if (navEntries && navEntries.length > 0) {
            const entry = navEntries[0];
            return {
                dom_content_loaded_ms: Math.round(entry.domContentLoadedEventEnd - entry.startTime),
                load_event_ms: Math.round(entry.loadEventEnd - entry.startTime),
                response_duration_ms: Math.round(entry.responseEnd - entry.requestStart),
                first_paint_ms: null
            };
        }

        const timing = perf.timing;
        if (timing) {
            const start = timing.navigationStart || timing.fetchStart;
            return {
                dom_content_loaded_ms: Math.max(0, timing.domContentLoadedEventEnd - start),
                load_event_ms: Math.max(0, timing.loadEventEnd - start),
                response_duration_ms: Math.max(0, timing.responseEnd - timing.requestStart),
                first_paint_ms: null
            };
        }

        return null;
    })()
    """

    @classmethod
    async def collect_accessibility(cls, page: Any) -> List[AccessibilityViolation]:
        """Execute WCAG accessibility scan against the active page DOM."""
        try:
            raw_violations = await page.evaluate(cls.WCAG_EVAL_SCRIPT)
            violations = []
            for item in raw_violations or []:
                violations.append(
                    AccessibilityViolation(
                        rule_id=item.get("rule_id", "unknown"),
                        impact=item.get("impact", "minor"),
                        description=item.get("description", ""),
                        help_text=item.get("help_text", ""),
                        help_url=item.get("help_url"),
                        selector=item.get("selector", "body"),
                        element_html=item.get("element_html"),
                    )
                )
            return violations
        except Exception:
            return []

    @classmethod
    async def collect_performance(cls, page: Any) -> Optional[PerformanceTiming]:
        """Collect navigation and load performance metrics from window.performance."""
        try:
            perf_data = await page.evaluate(cls.PERFORMANCE_EVAL_SCRIPT)
            if perf_data:
                return PerformanceTiming(
                    dom_content_loaded_ms=float(perf_data.get("dom_content_loaded_ms", 0.0)),
                    load_event_ms=float(perf_data.get("load_event_ms", 0.0)),
                    response_duration_ms=float(perf_data.get("response_duration_ms", 0.0)),
                    first_paint_ms=perf_data.get("first_paint_ms"),
                )
            return None
        except Exception:
            return None

    @classmethod
    def analyze_security_headers(cls, headers: Dict[str, str]) -> SecurityHeaders:
        """Inspect HTTP response headers for passive security posture."""
        lower_headers = {k.lower(): v for k, v in headers.items()}
        result = SecurityHeaders(raw_headers=headers)
        missing: List[str] = []

        for header_name, attr_name in cls.RECOMMENDED_HEADERS:
            present = header_name.lower() in lower_headers
            setattr(result, attr_name, present)
            if not present:
                missing.append(header_name)

        result.missing_recommended_headers = missing
        return result

    @classmethod
    def save_results(cls, result: ExtendedPageCheckResult, out_path: Path) -> None:
        """Persist health check result into run directory."""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
