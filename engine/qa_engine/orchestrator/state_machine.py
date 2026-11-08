"""Run state machine for the QA Engine orchestrator.

Manages the 11 sequential workflow stages and human gates (Gate 0, Gate 1, Gate 2).
Enforces that stages cannot be bypassed and broadcasts stage.update notifications.
"""

from enum import Enum
from typing import Any, Callable, Coroutine, Dict, Optional

from pydantic import BaseModel

from qa_engine.orchestrator.run_store import RunStore, ScopeModel


class Stage(str, Enum):
    STAGE_0_SCOPE = "STAGE_0_SCOPE"  # Gate 0
    STAGE_1_INTAKE = "STAGE_1_INTAKE"
    STAGE_2_ANALYSIS = "STAGE_2_ANALYSIS"  # Clarifications
    STAGE_3_EXPLORATION = "STAGE_3_EXPLORATION"
    STAGE_4_TEST_DESIGN = "STAGE_4_TEST_DESIGN"
    STAGE_5_REVIEW_LOOP = "STAGE_5_REVIEW_LOOP"  # Gate 1
    STAGE_6_SCRIPT_GEN = "STAGE_6_SCRIPT_GEN"  # Optional Script Review
    STAGE_7_DRY_RUN = "STAGE_7_DRY_RUN"
    STAGE_8_EXECUTION = "STAGE_8_EXECUTION"
    STAGE_9_INVESTIGATION = "STAGE_9_INVESTIGATION"
    STAGE_10_SIGN_OFF = "STAGE_10_SIGN_OFF"  # Gate 2
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class StateTransitionError(Exception):
    """Raised when an illegal or unauthorized stage transition is attempted."""

    pass


class RunState(BaseModel):
    run_id: str
    current_stage: Stage = Stage.STAGE_0_SCOPE
    scope_confirmed: bool = False
    testcases_approved: bool = False
    approved_testcases_hash: Optional[str] = None
    is_cancelled: bool = False


class OrchestrationStateMachine:
    """Controls run transitions, enforces gate requirements, and audits state changes."""

    def __init__(
        self,
        run_store: RunStore,
        notify_callback: Optional[
            Callable[[str, Dict[str, Any]], Coroutine[Any, Any, None]]
        ] = None,
    ):
        self.store = run_store
        self.state = RunState(run_id=self.store.run_id)
        self.notify_callback = notify_callback

    async def _emit_update(self, description: str) -> None:
        """Log event to audit trail and send stage.update notification to UI."""
        self.store.audit.log_event(
            stage=self.state.current_stage.value,
            event_type="STAGE_TRANSITION",
            actor="engine",
            details={"stage": self.state.current_stage.value, "description": description},
        )
        if self.notify_callback:
            await self.notify_callback(
                "stage.update",
                {
                    "run_id": self.state.run_id,
                    "stage": self.state.current_stage.value,
                    "status": "active"
                    if self.state.current_stage
                    not in (Stage.COMPLETED, Stage.CANCELLED, Stage.ERROR)
                    else "finished",
                    "description": description,
                },
            )

    async def confirm_scope(self, scope: ScopeModel) -> None:
        """Gate 0: Confirm scope, domain allowlist, and legal authorization attestation."""
        if self.state.current_stage != Stage.STAGE_0_SCOPE:
            raise StateTransitionError(f"Cannot confirm scope in stage {self.state.current_stage}")

        if not scope.authorized_attestation:
            raise StateTransitionError(
                "Gate 0 failed: User must explicitly attest authorization to test the target."
            )

        self.store.save_scope(scope)
        self.state.scope_confirmed = True
        self.store.audit.log_event(
            stage=Stage.STAGE_0_SCOPE.value,
            event_type="GATE_0_SCOPE_CONFIRMED",
            actor="engineer",
            details={
                "start_url": scope.start_url,
                "allowed_domains": scope.allowed_domains,
                "environment": scope.environment,
            },
        )
        self.state.current_stage = Stage.STAGE_1_INTAKE
        await self._emit_update("Scope confirmed. Proceeding to requirement intake.")

    async def advance_to(self, target_stage: Stage, description: str = "") -> None:
        """Advance state machine validating prerequisites."""
        if self.state.is_cancelled:
            raise StateTransitionError("Cannot advance a cancelled run.")

        # Guard Gate 0
        if target_stage != Stage.STAGE_0_SCOPE and not self.state.scope_confirmed:
            raise StateTransitionError(
                "Cannot proceed beyond Stage 0 without confirming scope (Gate 0)."
            )

        # Guard Gate 1: Cannot generate scripts or run tests without approved test cases
        if target_stage in (
            Stage.STAGE_6_SCRIPT_GEN,
            Stage.STAGE_7_DRY_RUN,
            Stage.STAGE_8_EXECUTION,
        ):
            if not self.state.testcases_approved:
                raise StateTransitionError(
                    "Cannot proceed to script generation or execution without Gate 1 approval."
                )

        self.state.current_stage = target_stage
        await self._emit_update(description or f"Entered {target_stage.value}")

    async def approve_testcases(self, version: int, approver: str, sha256_hash: str) -> None:
        """Gate 1: Record test case approval bound to content hash."""
        if self.state.current_stage != Stage.STAGE_5_REVIEW_LOOP:
            raise StateTransitionError(
                f"Cannot approve test cases in stage {self.state.current_stage}"
            )

        self.state.testcases_approved = True
        self.state.approved_testcases_hash = sha256_hash

        approval_data = {
            "version": version,
            "approver": approver,
            "sha256_hash": sha256_hash,
        }
        self.store.write_json_atomic("approvals.json", approval_data)
        self.store.audit.log_event(
            stage=Stage.STAGE_5_REVIEW_LOOP.value,
            event_type="GATE_1_TESTCASES_APPROVED",
            actor=approver,
            details=approval_data,
        )
        self.state.current_stage = Stage.STAGE_6_SCRIPT_GEN
        await self._emit_update(f"Gate 1 passed: Test cases v{version} approved by {approver}.")

    async def sign_off_gate_2(
        self,
        failure_id: str,
        approver: str,
        defect_confirmed: bool,
        notes: Optional[str] = None,
    ) -> None:
        """Gate 2: Human engineer sign-off on product defect failure before filing bug."""
        self.store.audit.log_event(
            stage=Stage.STAGE_10_SIGN_OFF.value,
            event_type="GATE_2_DEFECT_SIGNOFF",
            actor=approver,
            details={
                "failure_id": failure_id,
                "defect_confirmed": defect_confirmed,
                "notes": notes,
            },
        )
        status_msg = "confirmed" if defect_confirmed else "rejected/dismissed"
        await self._emit_update(
            f"Gate 2: Defect {failure_id} {status_msg} by {approver}."
        )

    async def cancel(self, reason: str = "User requested cancellation") -> None:
        """Cancel current execution and log reason."""
        self.state.is_cancelled = True
        self.state.current_stage = Stage.CANCELLED
        self.store.audit.log_event(
            stage=Stage.CANCELLED.value,
            event_type="RUN_CANCELLED",
            actor="engineer",
            details={"reason": reason},
        )
        await self._emit_update(f"Run cancelled: {reason}")
