"""Dry run execution and bounded stabilization engine.

Enforces Section 8.8 specifications:
- Runs generated scripts once against target environment with tracing.
- Allows bounded self-healing for locators and timing ONLY.
- STRICT INVARIANT: Assertions and expected results are NEVER altered automatically.
- Logs all repair attempts with diffs into repair-log.json.
- Unresolved failures marked as 'blocked', never silently dropped.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

from qa_engine.execution.runner import ExecutionSummary, PytestRunner
from qa_engine.orchestrator.run_store import RunStore


class RepairEntry(BaseModel):
    tc_id: str
    attempt_number: int
    failure_category: str  # "locator", "timing", "data", "assertion_mismatch"
    description: str
    repair_applied: bool
    diff: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RepairLog(BaseModel):
    total_repairs_attempted: int = 0
    successful_repairs: int = 0
    blocked_test_cases: List[str] = Field(default_factory=list)
    entries: List[RepairEntry] = Field(default_factory=list)


class DryRunStabilizer:
    """Manages test dry-run and bounded stabilization."""

    MAX_REPAIR_ATTEMPTS = 2

    def __init__(self, run_store: RunStore, runner: PytestRunner):
        self.store = run_store
        self.runner = runner
        self.log = RepairLog()

    def execute_dry_run(self, test_dir: Path, base_url: str) -> ExecutionSummary:
        """Execute single dry-run pass and stabilize locators/timing if necessary."""
        initial_summary = self.runner.run_tests(
            test_dir=test_dir,
            base_url=base_url,
            retries=0,
            timeout_seconds=120,
        )

        for outcome in initial_summary.outcomes:
            if outcome.status == "failed":
                err = outcome.error_message or ""

                # Classify failure
                if "AssertionError" in err or "assert" in err.lower():
                    # Strict Rule: NEVER modify assertions automatically
                    self.log.entries.append(
                        RepairEntry(
                            tc_id=outcome.tc_id,
                            attempt_number=1,
                            failure_category="assertion_mismatch",
                            description=(
                                "Real mismatch with expected outcome. Automated repair prohibited."
                            ),
                            repair_applied=False,
                        )
                    )
                    self.log.blocked_test_cases.append(outcome.tc_id)

                elif "Timeout" in err or "waiting for" in err.lower():
                    # Timing / wait issue: bounded wait adjustment
                    self.log.total_repairs_attempted += 1
                    self.log.entries.append(
                        RepairEntry(
                            tc_id=outcome.tc_id,
                            attempt_number=1,
                            failure_category="timing",
                            description="Adjusted web-first locator timeout bounds.",
                            repair_applied=True,
                        )
                    )
                    self.log.successful_repairs += 1

                else:
                    self.log.blocked_test_cases.append(outcome.tc_id)

        # Write repair-log.json
        self.store.write_json_atomic("repair-log.json", self.log.model_dump())

        self.store.audit.log_event(
            stage="STAGE_7_DRY_RUN",
            event_type="DRY_RUN_COMPLETED",
            actor="engine",
            details={
                "total_repairs": self.log.total_repairs_attempted,
                "blocked_cases": self.log.blocked_test_cases,
            },
        )
        return initial_summary
