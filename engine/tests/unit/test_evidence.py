"""Unit tests for EvidenceIndex, verified citation tracking, and hashing."""

from qa_engine.investigation.evidence import EvidenceIndex


def test_evidence_registration_and_hashing(tmp_path):
    run_dir = tmp_path / "run-001"
    screenshots_dir = run_dir / "evidence" / "screenshots"
    screenshots_dir.mkdir(parents=True)

    test_png = screenshots_dir / "login_error.png"
    test_png.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRtestdata")

    index = EvidenceIndex()
    item = index.register_file(
        file_path=test_png,
        base_dir=run_dir,
        category="screenshot",
        description="Login page failure screenshot",
    )

    assert item.evidence_id == "EV-001"
    assert item.mime_type == "image/png"
    assert item.relative_path == "evidence/screenshots/login_error.png"
    assert item.sha256 is not None
    assert len(item.sha256) == 64  # SHA-256 length in hex
    assert item.file_size_bytes > 0


def test_inline_text_registration(tmp_path):
    run_dir = tmp_path / "run-001"
    index = EvidenceIndex()

    item = index.register_inline_text(
        content="Console Error: Uncaught TypeError: undefined is not a function",
        base_dir=run_dir,
        filename="console_errors.log",
        category="console_log",
        description="Captured JavaScript runtime exceptions",
    )

    assert item.evidence_id == "EV-001"
    assert item.category == "console_log"
    assert item.mime_type == "text/plain"
    assert (run_dir / item.relative_path).exists()


def test_citation_verification(tmp_path):
    run_dir = tmp_path / "run-001"
    index = EvidenceIndex()

    index.register_inline_text(
        content="Stack trace",
        base_dir=run_dir,
        filename="stack.log",
        category="error",
        description="Stack trace",
    )

    # Valid citations
    assert index.verify_citation("EV-001")
    assert index.verify_citation("[EV-001]")

    # Invalid / hallucinated citations
    assert not index.verify_citation("EV-999")
    assert not index.verify_citation("[EV-002]")

    valid = index.get_valid_citations(["EV-001", "EV-999", "[EV-001]", "phantom"])
    assert valid == ["EV-001", "EV-001"]


def test_scan_run_directory(tmp_path):
    run_dir = tmp_path / "run-002"
    screenshots_dir = run_dir / "evidence" / "screenshots"
    traces_dir = run_dir / "evidence" / "traces"
    screenshots_dir.mkdir(parents=True)
    traces_dir.mkdir(parents=True)

    (screenshots_dir / "step1.png").write_bytes(b"dummy image")
    (traces_dir / "trace1.zip").write_bytes(b"PK\x03\x04dummy zip")

    index = EvidenceIndex()
    index.scan_run_directory(run_dir)

    assert len(index.items) == 2
    categories = [i.category for i in index.items.values()]
    assert "screenshot" in categories
    assert "trace" in categories


def test_evidence_persistence_roundtrip(tmp_path):
    run_dir = tmp_path / "run-003"
    index = EvidenceIndex()
    index.register_inline_text(
        content="network failure",
        base_dir=run_dir,
        filename="net.log",
        category="network_log",
        description="network",
    )

    save_path = run_dir / "evidence_index.json"
    index.save(save_path)

    loaded = EvidenceIndex.load(save_path)
    assert len(loaded.items) == 1
    assert "EV-001" in loaded.items
    assert loaded.items["EV-001"].category == "network_log"
