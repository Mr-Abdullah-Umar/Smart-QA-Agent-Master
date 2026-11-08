"""Token and sensitive data redaction engine for the QA Engine.

Enforces T6 and T7 controls: strips credentials, secrets, API tokens,
and PII (emails, credit cards) before sending prompts to the LLM
or writing traces/reports to disk.
"""

import re
from typing import Dict, List, Tuple

from pydantic import BaseModel, Field


class RedactionRecord(BaseModel):
    category: str
    count: int = 0
    masked_placeholders: List[str] = Field(default_factory=list)


class RedactionReport(BaseModel):
    total_redacted: int = 0
    categories: Dict[str, RedactionRecord] = Field(default_factory=dict)


class RedactionEngine:
    """Regex-based scanner for confidential and personally identifiable tokens."""

    PATTERNS: List[Tuple[str, re.Pattern, str]] = [
        # Generic API keys and client secrets
        (
            "api_key",
            re.compile(
                r'(?i)(["\']?(?:api[_-]?key|client[_-]?secret|auth[_-]?token)["\']?\s*[:=]\s*["\'])([^"\'\s]+)(["\'])'
            ),
            r"\g<1>[REDACTED_API_KEY]\g<3>",
        ),
        # Passwords in JSON / query params / config strings
        (
            "password",
            re.compile(
                r'(?i)(["\']?(?:password|passwd|pwd|token)["\']?\s*[:=]\s*["\'])([^"\'\s]+)(["\'])'
            ),
            r"\g<1>[REDACTED_SECRET]\g<3>",
        ),
        # Bearer tokens / Authorization headers
        (
            "auth_header",
            re.compile(r"(?i)(Authorization:\s*Bearer\s+)([A-Za-z0-9\-\._~\+\/]+=*)"),
            r"\g<1>[REDACTED_BEARER_TOKEN]",
        ),
        # Credit card numbers (Luhn candidate strings: 13-19 digits with optional spaces/dashes)
        (
            "credit_card",
            re.compile(r"\b(?:\d{4}[ -]?){3,4}\d{1,4}\b"),
            "[REDACTED_CREDIT_CARD]",
        ),
        # Email addresses
        (
            "email",
            re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b"),
            "[REDACTED_EMAIL]",
        ),
    ]

    @classmethod
    def redact(cls, text: str) -> Tuple[str, RedactionReport]:
        """Redact sensitive patterns from text and return cleaned text plus a RedactionReport."""
        if not text:
            return "", RedactionReport()

        report = RedactionReport()
        cleaned = text

        for category, pattern, replacement in cls.PATTERNS:
            matches = list(pattern.finditer(cleaned))
            count = len(matches)
            if count > 0:
                cleaned = pattern.sub(replacement, cleaned)
                report.total_redacted += count
                record = report.categories.setdefault(
                    category, RedactionRecord(category=category, count=0)
                )
                record.count += count
                if replacement not in record.masked_placeholders:
                    record.masked_placeholders.append(replacement)

        return cleaned, report
