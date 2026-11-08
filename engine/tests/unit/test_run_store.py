"""Unit tests for RunStore lifecycle and atomic writes."""

from qa_engine.orchestrator.run_store import RunStore, ScopeModel


def test_run_store_folder_structure(tmp_path):
    store = RunStore(workspace_root=tmp_path, run_id="test-run-001")

    assert (store.run_dir / "testcases").exists()
    assert (store.run_dir / "scripts" / "pages").exists()
    assert (store.run_dir / "scripts" / "tests").exists()
    assert (store.run_dir / "results").exists()
    assert (store.run_dir / "evidence" / "screenshots").exists()
    assert (store.run_dir / "report").exists()


def test_run_store_atomic_write_and_read(tmp_path):
    store = RunStore(workspace_root=tmp_path, run_id="test-run-001")

    content = "# Requirement Document\nTest the login workflow."
    store.write_atomic("requirement.md", content)

    read_back = store.read_text("requirement.md")
    assert read_back == content


def test_run_store_scope_persistence(tmp_path):
    store = RunStore(workspace_root=tmp_path, run_id="test-run-001")

    scope = ScopeModel(
        start_url="https://test.example.com",
        allowed_domains=["test.example.com"],
        environment="test",
        authorized_attestation=True,
    )
    store.save_scope(scope)

    loaded = store.load_scope()
    assert loaded.start_url == "https://test.example.com"
    assert loaded.allowed_domains == ["test.example.com"]
    assert loaded.authorized_attestation is True
