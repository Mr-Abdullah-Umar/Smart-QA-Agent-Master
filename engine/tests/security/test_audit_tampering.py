"""Security Penetration: Tamper-Evident Audit Trail Integrity (Appendix E Checklist).

Verifies T11/T12 controls:
- Cryptographic SHA-256 hash-chain binding each log entry to the previous entry.
- Immediate detection of record insertion, modification, deletion, reordering, or corruption.
"""

import json

from qa_engine.orchestrator.audit import AuditLogger


def test_audit_log_clean_verification(tmp_path):
    log_file = tmp_path / "audit.jsonl"
    logger = AuditLogger(log_file)

    logger.log_event("STAGE_0", "SCOPE_SET", "engineer", {"target": "https://example.com"})
    logger.log_event("STAGE_1", "INTAKE_DONE", "engine", {"chars": 500})
    logger.log_event("STAGE_5", "GATE_1_APPROVED", "lead", {"version": 1})

    is_valid, error = logger.verify_log_file(log_file)
    assert is_valid is True
    assert error is None


def test_audit_log_tampered_payload_detection(tmp_path):
    log_file = tmp_path / "audit.jsonl"
    logger = AuditLogger(log_file)

    logger.log_event("STAGE_0", "SCOPE_SET", "engineer", {"target": "https://example.com"})
    logger.log_event("STAGE_1", "INTAKE_DONE", "engine", {"chars": 500})
    logger.log_event("STAGE_5", "GATE_1_APPROVED", "lead", {"version": 1})

    # Adversary modifies payload of line 2
    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    record1 = json.loads(lines[1])
    record1["details"]["chars"] = 999999  # Tampered
    lines[1] = json.dumps(record1)
    log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    is_valid, error = logger.verify_log_file(log_file)
    assert is_valid is False
    assert "Tampered content" in (error or "")


def test_audit_log_deleted_record_detection(tmp_path):
    log_file = tmp_path / "audit.jsonl"
    logger = AuditLogger(log_file)

    logger.log_event("STAGE_0", "EVENT_0", "user", {})
    logger.log_event("STAGE_1", "EVENT_1", "user", {})
    logger.log_event("STAGE_2", "EVENT_2", "user", {})

    # Adversary deletes line 1 (the middle record)
    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    del lines[1]
    log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    is_valid, error = logger.verify_log_file(log_file)
    assert is_valid is False
    assert "Non-sequential entry_id" in (error or "")


def test_audit_log_reordered_records_detection(tmp_path):
    log_file = tmp_path / "audit.jsonl"
    logger = AuditLogger(log_file)

    logger.log_event("STAGE_0", "EVENT_0", "user", {})
    logger.log_event("STAGE_1", "EVENT_1", "user", {})

    # Adversary swaps lines
    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    lines[0], lines[1] = lines[1], lines[0]
    log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    is_valid, error = logger.verify_log_file(log_file)
    assert is_valid is False
