"""End-to-End Pilot Simulation & Section 13 Benchmark Evaluation.

Simulates a complete enterprise application QA lifecycle:
- Gate 0 scope attestation.
- PII and credential redaction.
- Test design with 100% traceability.
- Gate 1 SHA-256 cryptographic binding.
- Page Object Model script generation and AST security validation.
- Execution, Evidence Indexing, and Appendix B Failure Investigation.
- Gate 2 Product Defect sign-off.
- Multi-format reporting (zero-JS HTML, Markdown, JSON, JUnit XML).
- Validation of Section 13 target benchmarks.
"""

import pytest

from qa_engine.execution.runner import ExecutionSummary, TestCaseOutcome
from qa_engine.generation.scriptgen import ScriptGenerator
from qa_engine.generation.testcases import TestCase, TestCaseCollection
from qa_engine.generation.validator import ASTSecurityValidator
from qa_engine.investigation.classifier import FailureClassifier
from qa_engine.investigation.evidence import EvidenceIndex
from qa_engine.investigation.schemas import FailureCategory
from qa_engine.orchestrator.run_store import RunStore, ScopeModel
from qa_engine.orchestrator.state_machine import OrchestrationStateMachine, Stage
from qa_engine.reporting.builder import ReportBuilder
from qa_engine.security.redaction import RedactionEngine


@pytest.mark.asyncio
async def test_complete_pilot_workflow_and_benchmarks(tmp_path):
    workspace = tmp_path / "pilot_workspace"
    workspace.mkdir()
    run_id = "pilot-run-2026-001"

    # Step 1: Initialize Run Store & State Machine
    store = RunStore(workspace_root=str(workspace), run_id=run_id)
    sm = OrchestrationStateMachine(run_store=store)
    assert sm.state.current_stage == Stage.STAGE_0_SCOPE

    # Step 2: Gate 0 Scope Confirmation & Legal Attestation
    scope = ScopeModel(
        start_url="https://shop.example.com",
        allowed_domains=["shop.example.com", "cdn.example.com"],
        environment="staging",
        authorized_attestation=True,
    )
    await sm.confirm_scope(scope)
    assert sm.state.current_stage == Stage.STAGE_1_INTAKE
    assert sm.state.scope_confirmed is True

    # Step 3: Requirement Intake & Redaction
    raw_requirement = (
        "Verify checkout flow with user test_admin and password: 'SuperSecretKey123!' "
        "Credit card 4532-1234-5678-9012 should process successfully."
    )
    redacted_req, report = RedactionEngine.redact(raw_requirement)
    assert "SuperSecretKey123!" not in redacted_req
    assert "4532-1234-5678-9012" not in redacted_req
    assert report.total_redacted > 0
    store.write_atomic("requirement.md", redacted_req)

    # Step 4: Advance to Test Design (Stage 4) & Draft Cases
    await sm.advance_to(Stage.STAGE_4_TEST_DESIGN)
    test_cases = [
        TestCase(
            tc_id="TC-CHECKOUT-001",
            title="Complete valid card checkout",
            requirement_ref="REQ-CHECKOUT-01",
            category="Functional positive",
            priority="P1",
            priority_rationale="Core e-commerce revenue flow",
            steps=["Add item to cart", "Proceed to checkout", "Submit valid payment"],
            expected_result="Order confirmation page displayed with order number",
        ),
        TestCase(
            tc_id="TC-CHECKOUT-002",
            title="Reject expired card checkout",
            requirement_ref="REQ-CHECKOUT-02",
            category="Functional negative",
            priority="P2",
            steps=["Add item to cart", "Submit expired payment card"],
            expected_result="Validation error: Card has expired",
        ),
    ]
    collection = TestCaseCollection(version=1, testcases=test_cases)
    store.write_atomic("testcases/v1.json", collection.model_dump_json(indent=2))

    # Benchmark: 100% Traceability
    for tc in collection.testcases:
        assert tc.requirement_ref.startswith("REQ-")

    # Step 5: Advance to Review Loop (Stage 5) and Gate 1 Approval
    await sm.advance_to(Stage.STAGE_5_REVIEW_LOOP)
    content_hash = collection.compute_canonical_hash()
    await sm.approve_testcases(
        version=1,
        approver="qa.lead@example.com",
        sha256_hash=content_hash,
    )
    assert sm.state.testcases_approved is True
    assert sm.state.current_stage == Stage.STAGE_6_SCRIPT_GEN

    # Step 6: Script Generation & AST Security Validation
    generated_dict = ScriptGenerator.write_scripts(
        store.run_dir / "scripts", collection.testcases, "checkout"
    )
    assert len(generated_dict) == 2  # page object + test script

    # Validate generated scripts through AST security validator
    for path in generated_dict.values():
        code = path.read_text(encoding="utf-8")
        val_result = ASTSecurityValidator.validate_script(code)
        assert val_result.is_valid is True, f"Script failed AST: {val_result.errors}"

    # Step 7: Advance to Execution (Stage 8) & Record Outcomes
    await sm.advance_to(Stage.STAGE_8_EXECUTION)
    summary = ExecutionSummary(
        total_tests=2,
        passed=1,
        failed=1,
        flaky=0,
        skipped=0,
        duration_seconds=4.8,
        outcomes=[
            TestCaseOutcome(
                tc_id="TC-CHECKOUT-001",
                status="passed",
                duration_seconds=2.1,
            ),
            TestCaseOutcome(
                tc_id="TC-CHECKOUT-002",
                status="failed",
                duration_seconds=2.7,
                error_message=(
                    "AssertionError: Expected 'Card has expired' but got '500 Internal Error'"
                ),
                stack_trace="checkout.py:45 in test_expired_card\nAssertionError",
            ),
        ],
    )

    # Step 8: Evidence Indexing
    evidence_index = EvidenceIndex()
    ev_screenshot = evidence_index.register_inline_text(
        content="Screenshot data placeholder",
        base_dir=store.run_dir,
        filename="checkout_failure.png",
        category="screenshot",
        description="Checkout error screen showing 500 error",
    )
    assert ev_screenshot.evidence_id == "EV-001"

    # Step 9: Investigation & Root Cause Analysis (Stage 9)
    await sm.advance_to(Stage.STAGE_9_INVESTIGATION)
    classifier = FailureClassifier(evidence_index=evidence_index)
    investigation = classifier.investigate(summary.outcomes[1])

    assert investigation.category == FailureCategory.PRODUCT_DEFECT
    assert investigation.requires_human_signoff is True
    assert investigation.gate_2_signed_off is False
    assert len(investigation.facts) > 0
    # Every cited fact MUST be a verified evidence ID
    for fact in investigation.facts:
        assert evidence_index.verify_citation(fact.evidence_id)

    # Step 10: Gate 2 Human Sign-off (Stage 10)
    await sm.advance_to(Stage.STAGE_10_SIGN_OFF)
    await sm.sign_off_gate_2(
        failure_id=investigation.failure_id,
        approver="engineer@example.com",
        defect_confirmed=True,
        notes="Confirmed checkout crash on expired card input. Bug logged.",
    )
    classifier.sign_off_defect(
        failure_id=investigation.failure_id,
        approver="engineer@example.com",
        notes="Confirmed checkout crash on expired card input. Bug logged.",
    )
    assert investigation.gate_2_signed_off is True

    # Step 11: Multi-Format Report Generation
    builder = ReportBuilder()
    payload = builder.prepare_payload(
        run_id=run_id,
        target_url="https://shop.example.com",
        summary=summary,
        test_collection=collection,
        investigations=[investigation],
        gate_1_hash=sm.state.approved_testcases_hash,
        audit_count=store.audit.current_entry_id,
        audit_hash_head=store.audit.last_hash,
    )

    written = builder.write_all_reports(payload, store)
    assert written["html"].exists()
    assert written["markdown"].exists()
    assert written["json"].exists()
    assert written["junit"].exists()

    # Enforce HTML zero-JS invariant
    html_content = written["html"].read_text(encoding="utf-8")
    assert "<script" not in html_content.lower()
    assert "AI QA Testing Harness" in html_content

    # Step 12: Verify Section 13 Success Benchmarks
    # 1. Test-case acceptance rate >= 80% (here 100% approved)
    assert sm.state.testcases_approved is True
    # 2. Traceability = 100%
    assert all(tc.requirement_ref for tc in collection.testcases)
    # 3. Investigation evidence validity = 100%
    assert all(evidence_index.verify_citation(c) for c in investigation.evidence_citations)
    # 4. Tamper-evident audit integrity = 100%
    is_valid, err = store.audit.verify_log_file(store.run_dir / "audit.jsonl")
    assert is_valid is True, f"Audit trail failed verification: {err}"
