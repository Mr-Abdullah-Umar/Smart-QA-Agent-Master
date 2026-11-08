"""Unit tests for OrchestrationStateMachine and Gate enforcement."""

import pytest

from qa_engine.orchestrator.run_store import RunStore, ScopeModel
from qa_engine.orchestrator.state_machine import (
    OrchestrationStateMachine,
    Stage,
    StateTransitionError,
)


@pytest.mark.asyncio
async def test_gate_0_scope_confirmation_enforced(tmp_path):
    store = RunStore(workspace_root=tmp_path, run_id="run-sm-001")
    sm = OrchestrationStateMachine(run_store=store)

    assert sm.state.current_stage == Stage.STAGE_0_SCOPE

    # Attempting to bypass Stage 0 without confirming scope must raise StateTransitionError
    with pytest.raises(
        StateTransitionError, match="Cannot proceed beyond Stage 0 without confirming scope"
    ):
        await sm.advance_to(Stage.STAGE_3_EXPLORATION)

    # Attempting to confirm scope without legal attestation must fail
    unauthorized_scope = ScopeModel(
        start_url="https://app.example.com",
        allowed_domains=["app.example.com"],
        authorized_attestation=False,
    )
    with pytest.raises(StateTransitionError, match="User must explicitly attest authorization"):
        await sm.confirm_scope(unauthorized_scope)

    # Valid attestation succeeds
    valid_scope = ScopeModel(
        start_url="https://app.example.com",
        allowed_domains=["app.example.com"],
        authorized_attestation=True,
    )
    await sm.confirm_scope(valid_scope)
    assert sm.state.current_stage == Stage.STAGE_1_INTAKE
    assert sm.state.scope_confirmed is True


@pytest.mark.asyncio
async def test_gate_1_testcase_approval_enforced(tmp_path):
    store = RunStore(workspace_root=tmp_path, run_id="run-sm-002")
    sm = OrchestrationStateMachine(run_store=store)

    valid_scope = ScopeModel(
        start_url="https://app.example.com",
        allowed_domains=["app.example.com"],
        authorized_attestation=True,
    )
    await sm.confirm_scope(valid_scope)

    # Progress through stages to review loop
    await sm.advance_to(Stage.STAGE_2_ANALYSIS)
    await sm.advance_to(Stage.STAGE_3_EXPLORATION)
    await sm.advance_to(Stage.STAGE_4_TEST_DESIGN)
    await sm.advance_to(Stage.STAGE_5_REVIEW_LOOP)

    # Attempting to proceed to script generation without approving test cases must fail
    with pytest.raises(StateTransitionError, match="without Gate 1 approval"):
        await sm.advance_to(Stage.STAGE_6_SCRIPT_GEN)

    # Approve test cases with hash
    testcases_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    await sm.approve_testcases(version=1, approver="alice@qa", sha256_hash=testcases_hash)

    assert sm.state.testcases_approved is True
    assert sm.state.current_stage == Stage.STAGE_6_SCRIPT_GEN
