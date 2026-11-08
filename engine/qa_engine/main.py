"""Entry point for the Python QA Engine.

Runs as a local child process started by the VS Code extension.
Communicates strictly over standard input/output using JSON-RPC 2.0.
Opens NO local TCP ports or network listeners.
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

from qa_engine.orchestrator.rpc import RPCDispatcher, StdioChannel
from qa_engine.orchestrator.run_store import RunStore, ScopeModel
from qa_engine.orchestrator.state_machine import OrchestrationStateMachine, Stage


class QAEngineServer:
    """Manages the lifecycle, RPC dispatch, and state machine of the active run."""

    def __init__(self):
        self.channel = StdioChannel()
        self.dispatcher = RPCDispatcher()
        self.run_store: Optional[RunStore] = None
        self.state_machine: Optional[OrchestrationStateMachine] = None
        self._register_handlers()

    def _register_handlers(self) -> None:
        self.dispatcher.register("run.start", self.handle_run_start)
        self.dispatcher.register("run.scope.confirm", self.handle_scope_confirm)
        self.dispatcher.register("run.cancel", self.handle_run_cancel)
        self.dispatcher.register("run.resume", self.handle_run_resume)
        self.dispatcher.register("run.testcases.approve", self.handle_testcases_approve)
        self.dispatcher.register("run.defect.signoff", self.handle_defect_signoff)

    async def _notify(self, method: str, params: Dict[str, Any]) -> None:
        """Send notification to VS Code extension."""
        await self.channel.send_notification(method, params)

    async def handle_run_start(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Initialize a new run with requirements and target information."""
        run_id = params.get("run_id", "run-default")
        workspace_root = params.get("workspace_root", str(Path.cwd()))
        requirement_text = params.get("requirement_text", "")
        start_url = params.get("start_url", "")
        allowed_domains = params.get("allowed_domains", [])

        self.run_store = RunStore(workspace_root=workspace_root, run_id=run_id)
        self.state_machine = OrchestrationStateMachine(
            run_store=self.run_store,
            notify_callback=self._notify,
        )

        # Write initial requirements if provided
        if requirement_text:
            self.run_store.write_atomic("requirement.md", requirement_text)

        self.run_store.audit.log_event(
            stage=Stage.STAGE_0_SCOPE.value,
            event_type="RUN_STARTED",
            actor="engineer",
            details={
                "run_id": run_id,
                "workspace_root": workspace_root,
                "start_url": start_url,
                "allowed_domains": allowed_domains,
            },
        )

        # Notify UI to present Scope Card (Gate 0)
        await self.channel.send_notification(
            "card.show",
            {
                "card_type": "scope_card",
                "run_id": run_id,
                "data": {
                    "start_url": start_url,
                    "allowed_domains": allowed_domains,
                },
            },
        )

        return {"status": "initialized", "run_id": run_id}

    async def handle_scope_confirm(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Process Gate 0 Scope Confirmation."""
        if not self.state_machine:
            raise RuntimeError("Engine not initialized with an active run.")

        scope_data = params.get("scope", {})
        scope = ScopeModel.model_validate(scope_data)
        await self.state_machine.confirm_scope(scope)
        return {"status": "confirmed", "stage": self.state_machine.state.current_stage.value}

    async def handle_testcases_approve(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Process Gate 1 Test Case Approval."""
        if not self.state_machine:
            raise RuntimeError("Engine not initialized with an active run.")

        version = params.get("version", 1)
        approver = params.get("approver", "engineer")
        sha256_hash = params.get("sha256_hash", "")

        await self.state_machine.approve_testcases(version, approver, sha256_hash)
        return {"status": "approved", "stage": self.state_machine.state.current_stage.value}

    async def handle_defect_signoff(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Process Gate 2 Defect Sign-off."""
        if not self.state_machine:
            raise RuntimeError("Engine not initialized with an active run.")

        failure_id = params.get("failure_id", "")
        approver = params.get("approver", "engineer")
        defect_confirmed = params.get("defect_confirmed", True)
        notes = params.get("notes")

        await self.state_machine.sign_off_gate_2(
            failure_id=failure_id,
            approver=approver,
            defect_confirmed=defect_confirmed,
            notes=notes,
        )
        return {"status": "signed_off", "failure_id": failure_id}

    async def handle_run_cancel(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Cancel active run."""
        reason = params.get("reason", "Cancelled by user")
        if self.state_machine:
            await self.state_machine.cancel(reason)
        return {"status": "cancelled"}

    async def handle_run_resume(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Resume an existing run from disk."""
        run_id = params.get("run_id")
        workspace_root = params.get("workspace_root", str(Path.cwd()))
        if not run_id:
            raise ValueError("run_id required to resume")

        self.run_store = RunStore(workspace_root=workspace_root, run_id=run_id)
        self.state_machine = OrchestrationStateMachine(
            run_store=self.run_store,
            notify_callback=self._notify,
        )

        # Verify audit trail
        valid, err = self.run_store.audit.verify_log_file(self.run_store.run_dir / "audit.jsonl")
        if not valid:
            raise ValueError(f"Audit log verification failed: {err}")

        # Check existing scope
        if (self.run_store.run_dir / "scope.json").exists():
            _ = self.run_store.load_scope()
            self.state_machine.state.scope_confirmed = True

        return {"status": "resumed", "run_id": run_id}

    async def run(self) -> None:
        """Main event loop: read requests from stdin and dispatch."""
        await self.channel.initialize()
        while True:
            line = await self.channel.read_line()
            if line is None:  # EOF on stdin (parent closed connection)
                break
            response = await self.dispatcher.handle_payload(line)
            if response is not None:
                await self.channel.send_response(response)


def main():
    server = QAEngineServer()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
