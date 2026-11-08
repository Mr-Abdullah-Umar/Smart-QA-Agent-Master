"""Unit tests for tamper-evident hash-chained audit logging."""

import json

from qa_engine.orchestrator.audit import AuditLogger


def test_audit_hash_chain_creation(tmp_path):
    log_file = tmp_path / "audit.jsonl"
    logger = AuditLogger(log_file)

    entry1 = logger.log_event(
        "STAGE_0_SCOPE", "SCOPE_CONFIRMED", "engineer", {"domain": "example.com"}
    )
    assert entry1.entry_id == 1
    assert entry1.prev_hash == AuditLogger.GENESIS_HASH
    assert len(entry1.sha256_hash) == 64

    entry2 = logger.log_event("STAGE_1_INTAKE", "REQUIREMENT_PARSED", "engine", {"length": 150})
    assert entry2.entry_id == 2
    assert entry2.prev_hash == entry1.sha256_hash
    assert len(entry2.sha256_hash) == 64

    # Verify chain integrity
    is_valid, err = AuditLogger.verify_log_file(log_file)
    assert is_valid is True
    assert err is None


def test_audit_detects_tampering(tmp_path):
    log_file = tmp_path / "audit.jsonl"
    logger = AuditLogger(log_file)

    logger.log_event("STAGE_0_SCOPE", "SCOPE_CONFIRMED", "engineer", {"domain": "example.com"})
    logger.log_event("STAGE_1_INTAKE", "REQUIREMENT_PARSED", "engine", {"length": 150})

    # Tamper with the content of the first entry
    with open(log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    tampered_entry = json.loads(lines[0])
    tampered_entry["details"]["domain"] = "evil.com"  # Altered data!
    lines[0] = json.dumps(tampered_entry) + "\n"

    with open(log_file, "w", encoding="utf-8") as f:
        f.writelines(lines)

    # Verification must fail
    is_valid, err = AuditLogger.verify_log_file(log_file)
    assert is_valid is False
    assert "Tampered content" in err
