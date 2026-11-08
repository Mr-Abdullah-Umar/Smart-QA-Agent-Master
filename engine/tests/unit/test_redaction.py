"""Unit tests for token redaction engine (T6 & T7 controls)."""

from qa_engine.security.redaction import RedactionEngine


def test_password_redaction():
    text = '{"username": "admin", "password": "supersecretpassword123!"}'
    cleaned, report = RedactionEngine.redact(text)

    assert "supersecretpassword123!" not in cleaned
    assert "[REDACTED_SECRET]" in cleaned
    assert report.total_redacted >= 1
    assert "password" in report.categories


def test_bearer_token_redaction():
    text = "GET /api/v1 HTTP/1.1\nAuthorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz"
    cleaned, report = RedactionEngine.redact(text)

    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz" not in cleaned
    assert "[REDACTED_BEARER_TOKEN]" in cleaned
    assert "auth_header" in report.categories


def test_api_key_redaction():
    text = 'client_secret: "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"'
    cleaned, report = RedactionEngine.redact(text)

    assert "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6" not in cleaned
    assert "[REDACTED_API_KEY]" in cleaned
    assert "api_key" in report.categories


def test_pii_redaction():
    text = "Contact customer at support@example.com with card 4111 2222 3333 4444"
    cleaned, report = RedactionEngine.redact(text)

    assert "support@example.com" not in cleaned
    assert "4111 2222 3333 4444" not in cleaned
    assert "[REDACTED_EMAIL]" in cleaned
    assert "[REDACTED_CREDIT_CARD]" in cleaned
