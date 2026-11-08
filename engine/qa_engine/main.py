"""Entry point for the Python QA Engine.

Runs as a local child process started by the VS Code extension (or the CLI).
Communicates strictly over standard input/output using JSON-RPC 2.0.
Opens NO local TCP ports or network listeners.

Workflows:
- New suite:   run.start -> Gate 0 scope -> analysis/clarifications -> exploration -> design
               -> review/revise -> Gate 1 approve -> scripts -> execute -> report -> library
- Retest:      suite.retest   (all cases, or only the ones that failed last time)
- Regression:  regression.run (every stored suite, optionally filtered by test type)
"""

import asyncio
import functools
import json
import logging
import os
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Coroutine, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from qa_engine.browser.extended_checks import ExtendedChecksCollector
from qa_engine.browser.snapshot import SnapshotResult
from qa_engine.browser.tools import GuardedBrowserSession, detect_chrome_channel
from qa_engine.execution.dry_run import DryRunCaseResult, DryRunReport, run_dry_run
from qa_engine.execution.runner import ExecutionSummary, PytestRunner
from qa_engine.generation.actions import describe_action
from qa_engine.generation.auto_design import design_smoke_testcases, module_code
from qa_engine.generation.designer import (
    AITestDesigner,
    build_collection,
    build_coverage,
    parse_acceptance_criteria,
    required_secrets,
    unverified_locators,
)
from qa_engine.generation.diff import TestCaseDiffEngine
from qa_engine.generation.scriptgen import ScriptGenerator, test_function_name
from qa_engine.generation.testcases import TEST_TYPES, TestCaseCollection
from qa_engine.generation.validator import ScriptValidator
from qa_engine.investigation.classifier import FailureClassifier
from qa_engine.investigation.evidence import EvidenceIndex
from qa_engine.llm.bridge_provider import ExtensionBridgeProvider
from qa_engine.llm.provider import LLMProvider
from qa_engine.orchestrator.review import ReviewManager
from qa_engine.orchestrator.rpc import RemoteRPCError, RPCDispatcher, StdioChannel
from qa_engine.orchestrator.run_store import RunStore, ScopeModel
from qa_engine.orchestrator.state_machine import OrchestrationStateMachine, Stage
from qa_engine.orchestrator.suite_store import (
    SuiteApproval,
    SuiteRecord,
    SuiteRunSummary,
    SuiteStore,
    slugify,
)
from qa_engine.reporting.builder import ReportBuilder
from qa_engine.reporting.regression import (
    RegressionReport,
    RegressionSuiteResult,
    compare_statuses,
    write_regression_report,
)
from qa_engine.security.redaction import RedactionEngine
from qa_engine.security.ssrf import validate_destination_url

logger = logging.getLogger(__name__)

ENGINE_VERSION = "0.3.0"
SecretResolver = Callable[[SuiteRecord, List[str]], Awaitable[Dict[str, str]]]

UPDATE_SUITE_COMMENTS = (
    "The requirement and/or acceptance criteria of this existing suite were updated. Keep "
    "cases that still apply unchanged (same tc_id), update cases whose criterion changed, add "
    "cases for new criteria, and remove cases whose criterion no longer exists."
)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _origin(url: str) -> str:
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


def _require_approver(params: Dict[str, Any]) -> str:
    approver = str(params.get("approver") or "").strip()
    if not approver:
        raise ValueError("An approver identity is required (sign in with GitHub in VS Code).")
    return approver


@dataclass
class DesignSession:
    """In-memory state of a suite being designed (from Gate 0 until Gate 1)."""

    store: RunStore
    sm: OrchestrationStateMachine
    module: str
    slug: str
    requirement: str
    criteria_text: str
    design_mode: str
    options: Dict[str, Any]
    environment: str
    criteria: List[Dict[str, str]] = field(default_factory=list)
    clarifications: List[Dict[str, str]] = field(default_factory=list)
    snapshots: List[SnapshotResult] = field(default_factory=list)
    collection: Optional[TestCaseCollection] = None
    designer: Optional[AITestDesigner] = None
    pending_questions: Optional[asyncio.Future] = None
    base_collection: Optional[TestCaseCollection] = None
    pending_dry_run: Optional[asyncio.Future] = None
    dry_run_report: Optional[DryRunReport] = None


class QAEngineServer:
    """Manages RPC dispatch, design sessions, and suite executions."""

    def __init__(
        self,
        channel: Optional[StdioChannel] = None,
        llm: Optional[LLMProvider] = None,
        secret_resolver: Optional[SecretResolver] = None,
    ):
        self.channel = channel or StdioChannel()
        self.dispatcher = RPCDispatcher()
        self.llm: LLMProvider = llm or ExtensionBridgeProvider(self.channel)
        self.secret_resolver = secret_resolver or self._resolve_secrets_via_extension
        self.session: Optional[DesignSession] = None
        self.run_store: Optional[RunStore] = None
        self.state_machine: Optional[OrchestrationStateMachine] = None
        self._task: Optional[asyncio.Task] = None
        self._register_handlers()

    def _register_handlers(self) -> None:
        handlers = {
            "engine.info": self.handle_engine_info,
            "run.start": self.handle_run_start,
            "run.scope.confirm": self.handle_scope_confirm,
            "run.clarifications.answer": self.handle_clarifications_answer,
            "run.testcases.revise": self.handle_testcases_revise,
            "run.testcases.approve": self.handle_testcases_approve,
            "run.dryrun.decide": self.handle_dry_run_decide,
            "run.cancel": self.handle_run_cancel,
            "run.resume": self.handle_run_resume,
            "run.defect.signoff": self.handle_defect_signoff,
            "suites.list": self.handle_suites_list,
            "suite.get": self.handle_suite_get,
            "suite.delete": self.handle_suite_delete,
            "suite.retest": self.handle_suite_retest,
            "regression.run": self.handle_regression_run,
        }
        for method, handler in handlers.items():
            self.dispatcher.register(method, handler)

    # ------------------------------------------------------------------ messaging helpers

    async def _notify(self, method: str, params: Dict[str, Any]) -> None:
        await self.channel.send_notification(method, params)

    async def _say(self, text: str) -> None:
        await self._notify("message.stream", {"chunk": text, "complete": True})

    async def _log(self, line: str) -> None:
        await self._notify(
            "message.stream", {"chunk": line + "\n", "complete": False, "style": "log"}
        )

    async def _end_log(self) -> None:
        await self._notify("message.stream", {"chunk": "", "complete": True, "style": "log"})

    async def _card(self, card_type: str, run_id: str, data: Dict[str, Any]) -> None:
        await self._notify("card.show", {"card_type": card_type, "run_id": run_id, "data": data})

    @staticmethod
    def _options(params: Dict[str, Any]) -> Dict[str, Any]:
        source = {**params, **(params.get("options") or {})}
        return {
            "headed": bool(source.get("headed", True)),
            "slowmo_ms": int(source.get("slowmo_ms", 500)),
            "browser_channel": source.get("browser_channel", "chrome"),
            "ai_enabled": bool(source.get("ai_enabled", False)),
            "dry_run": bool(source.get("dry_run", True)),
        }

    @staticmethod
    def _browser_channel(options: Dict[str, Any]) -> Optional[str]:
        channel = options.get("browser_channel", "chrome") or None
        if channel == "chrome" and detect_chrome_channel() is None:
            return None
        return channel

    def _start_background(self, coro: Coroutine[Any, Any, None]) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = asyncio.create_task(self._guarded(coro))

    async def wait_idle(self) -> None:
        """Await the current background workflow (used by the CLI)."""
        while self._task and not self._task.done():
            await asyncio.gather(self._task, return_exceptions=True)

    async def _guarded(self, coro: Coroutine[Any, Any, None]) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Workflow failed")
            await self._end_log()
            await self._say(f"Run failed: {exc}")
            if self.state_machine and self.state_machine.state.current_stage not in (
                Stage.COMPLETED,
                Stage.CANCELLED,
            ):
                await self.state_machine.mark_error(str(exc))

    async def _resolve_secrets_via_extension(
        self, record: SuiteRecord, names: List[str]
    ) -> Dict[str, str]:
        try:
            result = await self.channel.request(
                "secrets.resolve",
                {"suite": record.slug, "module": record.module, "names": names},
                timeout=600,
            )
        except (RemoteRPCError, asyncio.TimeoutError) as exc:
            await self._say(f"Could not load suite secrets ({exc}); those tests will be blocked.")
            return {}
        values = (result or {}).get("values") or {}
        return {str(k).upper(): str(v) for k, v in values.items() if v}

    # ------------------------------------------------------------------ engine info

    async def handle_engine_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "version": ENGINE_VERSION,
            "chrome_installed": detect_chrome_channel() is not None,
            "capabilities": [
                "suites",
                "retest",
                "regression",
                "ai_design",
                "smoke_design",
                "dry_run",
                "suite_update",
                "suite_delete",
                "environments",
            ],
            "test_types": list(TEST_TYPES),
        }

    # ------------------------------------------------------------------ new suite design

    async def handle_run_start(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Start designing a suite: validate the target, then present the Gate 0 scope card."""
        start_url = str(params.get("start_url") or "").strip()
        if not start_url:
            raise ValueError("A start URL is required.")
        host = (urlparse(start_url).hostname or "").lower()
        allowed = [d.strip().lower() for d in params.get("allowed_domains") or [] if d.strip()]
        if host and host not in allowed:
            allowed.insert(0, host)
        ok, reason = validate_destination_url(start_url, allowed, resolve_dns=True)
        if not ok:
            raise ValueError(f"Target rejected by network policy: {reason}")

        workspace_root = params.get("workspace_root") or str(Path.cwd())
        module = str(params.get("module") or "").strip() or f"{host} smoke"
        options = self._options(params)
        design_mode = params.get("design_mode") or ("ai" if options["ai_enabled"] else "smoke")
        if design_mode == "ai" and not options["ai_enabled"]:
            raise ValueError("AI design needs a connected AI provider (open the AI Provider tab).")
        run_id = params.get("run_id") or f"run-{slugify(module)}-{_stamp()}"

        if self._task and not self._task.done():
            self._task.cancel()
        store = RunStore(workspace_root=workspace_root, run_id=run_id)
        sm = OrchestrationStateMachine(run_store=store, notify_callback=self._notify)
        self.run_store, self.state_machine = store, sm
        self.session = DesignSession(
            store=store,
            sm=sm,
            module=module,
            slug=slugify(module),
            requirement=str(params.get("requirement_text") or "").strip(),
            criteria_text=str(params.get("acceptance_criteria") or "").strip(),
            design_mode=design_mode,
            options=options,
            environment=str(params.get("environment") or "").strip(),
        )
        suites = SuiteStore(workspace_root)
        existing = suites.exists(self.session.slug)
        if existing:
            try:
                self.session.base_collection = suites.load_version(self.session.slug)
            except (FileNotFoundError, ValueError) as exc:
                logger.warning("Existing suite %s has no readable version: %s", module, exc)
        store.audit.log_event(
            stage=Stage.STAGE_0_SCOPE.value,
            event_type="RUN_STARTED",
            actor=str(params.get("approver") or "engine"),
            details={
                "run_id": run_id,
                "module": module,
                "design_mode": design_mode,
                "start_url": start_url,
                "allowed_domains": allowed,
            },
        )
        await self._card(
            "scope_card",
            run_id,
            {
                "module": module,
                "design_mode": design_mode,
                "updates_existing_suite": existing,
                "start_url": start_url,
                "allowed_domains": allowed,
                "environment": self.session.environment,
                "criteria_count": len(parse_acceptance_criteria(self.session.criteria_text)),
            },
        )
        return {"status": "initialized", "run_id": run_id, "module": module}

    async def handle_scope_confirm(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Gate 0: confirm scope, then analyze, explore, and design in the background."""
        session = self._require_session()
        approver = _require_approver(params)
        scope = ScopeModel.model_validate(params.get("scope", {}))
        if not scope.environment.strip():
            raise ValueError("Select the target environment before confirming scope.")
        scope.allowed_domains = [d.strip().lower() for d in scope.allowed_domains if d.strip()]
        ok, reason = validate_destination_url(scope.start_url, scope.allowed_domains, True)
        if not ok:
            raise ValueError(f"Scope rejected by network policy: {reason}")
        await session.sm.confirm_scope(scope, actor=approver)
        session.environment = scope.environment
        self._start_background(self._design_pipeline(session, scope))
        return {"status": "confirmed", "stage": session.sm.state.current_stage.value}

    def _require_session(self) -> DesignSession:
        if not self.session:
            raise RuntimeError("No suite is being designed. Start a new suite first.")
        return self.session

    async def _design_pipeline(self, session: DesignSession, scope: ScopeModel) -> None:
        store, sm = session.store, session.sm

        # Stage 1: intake & redaction
        requirement, req_report = RedactionEngine.redact(session.requirement)
        criteria_text, ac_report = RedactionEngine.redact(session.criteria_text)
        session.requirement = requirement
        session.criteria = parse_acceptance_criteria(criteria_text)
        store.write_atomic("requirement.md", self._requirement_md(session))
        store.write_json_atomic("criteria.json", session.criteria)
        redacted = req_report.total_redacted + ac_report.total_redacted
        await self._say(
            f"Module **{session.module}**: {len(session.criteria)} acceptance criteria received"
            f" ({redacted} sensitive token(s) redacted)."
        )

        # Stage 2: analysis & clarifications
        await sm.advance_to(Stage.STAGE_2_ANALYSIS, "Analyzing requirement and acceptance criteria")
        if session.design_mode == "ai":
            session.designer = AITestDesigner(
                self.llm, session.module, scope.start_url, scope.allowed_domains
            )
            if session.requirement or session.criteria:
                await self._say("Asking the AI provider to analyze the requirement ...")
                analysis = await session.designer.analyze(session.requirement, session.criteria)
                store.write_json_atomic("analysis.json", analysis.model_dump())
                await self._say(f"Analysis: {analysis.summary}")
                if analysis.clarification_questions:
                    await self._ask_clarifications(session, analysis.model_dump())
        else:
            store.write_json_atomic(
                "analysis.json",
                {"summary": f"Smoke suite for {scope.start_url}", "design_mode": "smoke"},
            )

        # Stage 3: exploration
        session.snapshots = await self._explore(session, scope)

        # Stage 4: design
        await sm.advance_to(Stage.STAGE_4_TEST_DESIGN, "Designing test cases")
        req_ref = f"REQ-{module_code(session.module)}"
        base = session.base_collection
        if session.designer and base and base.testcases:
            await self._say(
                f"Updating the existing suite ({len(base.testcases)} approved case(s)) to the new "
                "requirement and criteria ..."
            )
            answers = "".join(
                f"\nClarification - {c['question']} Answer: {c['answer']}"
                for c in session.clarifications
            )
            result = await session.designer.revise(
                base,
                UPDATE_SUITE_COMMENTS + answers,
                session.requirement,
                session.criteria,
                session.snapshots,
            )
            collection = build_collection(
                result, session.module, req_ref, existing_ids={tc.tc_id for tc in base.testcases}
            )
            changes = TestCaseDiffEngine.compute_diff(base, collection).generate_summary()
            await self._present_review(
                session,
                collection,
                diff_summary=f"Changes against approved suite v{base.version}: {changes}",
                revised=False,
            )
            return
        elif session.designer:
            await self._say("AI is designing test cases from the requirement and pages ...")
            result = await session.designer.design(
                session.requirement, session.criteria, session.clarifications, session.snapshots
            )
            collection = build_collection(result, session.module, req_ref)
        else:
            collection = design_smoke_testcases(
                session.snapshots[0], module=session.module, requirement_ref=req_ref
            )
        await self._present_review(session, collection, diff_summary=None, revised=False)

    @staticmethod
    def _requirement_md(session: DesignSession) -> str:
        lines = [f"# Module: {session.module}", "", "## Requirement", ""]
        lines.append(session.requirement or "_No requirement text provided._")
        lines += ["", "## Acceptance Criteria", ""]
        lines += [f"- **{c['id']}**: {c['text']}" for c in session.criteria] or ["_None._"]
        return "\n".join(lines) + "\n"

    async def _ask_clarifications(self, session: DesignSession, analysis: Dict[str, Any]) -> None:
        questions = analysis.get("clarification_questions") or []
        session.pending_questions = asyncio.get_running_loop().create_future()
        await self._card(
            "clarification_card",
            session.store.run_id,
            {"summary": analysis.get("summary", ""), "questions": questions},
        )
        answers: Dict[str, str] = await session.pending_questions
        session.pending_questions = None
        session.clarifications = [
            {
                "question": q.get("question_text", ""),
                "answer": answers.get(q.get("question_id", ""), "").strip() or "No answer given.",
            }
            for q in questions
        ]
        session.store.write_json_atomic("clarifications.json", session.clarifications)

    async def handle_clarifications_answer(self, params: Dict[str, Any]) -> Dict[str, Any]:
        session = self._require_session()
        if not session.pending_questions or session.pending_questions.done():
            raise RuntimeError("No clarification questions are pending.")
        approver = _require_approver(params)
        answers = {str(k): str(v) for k, v in (params.get("answers") or {}).items()}
        session.store.audit.log_event(
            stage=Stage.STAGE_2_ANALYSIS.value,
            event_type="CLARIFICATIONS_ANSWERED",
            actor=approver,
            details={"answered": len([v for v in answers.values() if v.strip()])},
        )
        session.pending_questions.set_result(answers)
        return {"status": "answered"}

    async def _explore(self, session: DesignSession, scope: ScopeModel) -> List[SnapshotResult]:
        store, sm, options = session.store, session.sm, session.options
        headed = options["headed"]
        channel = self._browser_channel(options)
        label = "Google Chrome" if channel == "chrome" else (channel or "Chromium")
        await sm.advance_to(
            Stage.STAGE_3_EXPLORATION,
            f"Exploring {scope.start_url} in {'visible' if headed else 'headless'} {label}",
        )
        browser = GuardedBrowserSession(
            allowed_domains=scope.allowed_domains,
            headless=not headed,
            evidence_dir=store.run_dir / "evidence" / "screenshots",
            channel=channel,
        )
        snapshots: List[SnapshotResult] = []
        a11y_count = 0
        try:
            await browser.initialize()
            first = await browser.navigate(scope.start_url)
            snapshots.append(first)
            await browser.screenshot("explore_01")
            a11y_count = len(await ExtendedChecksCollector.collect_accessibility(browser._page))
            if session.designer:
                links = await browser.list_links()
                max_extra = max(0, min(4, scope.max_pages - 1))
                urls = await session.designer.choose_pages(
                    session.requirement, session.criteria, first, links, max_pages=max_extra
                )
                for idx, url in enumerate(urls, start=2):
                    try:
                        snapshots.append(await browser.navigate(url))
                        await browser.screenshot(f"explore_{idx:02d}")
                        await self._say(f"Explored {url}")
                    except Exception as exc:  # noqa: BLE001
                        await self._say(f"Skipped {url}: {exc}")
            if headed:
                await asyncio.sleep(1)
        finally:
            await browser.close()

        store.write_json_atomic(
            "site-profile.json",
            {
                "pages": [
                    {
                        "url": s.url,
                        "title": s.title,
                        "interactive_elements": [e.model_dump() for e in s.elements.values()],
                    }
                    for s in snapshots
                ],
                "accessibility_observations": a11y_count,
            },
        )
        total = sum(s.total_interactive_elements for s in snapshots)
        titles = ", ".join(f"'{s.title}'" for s in snapshots[:3])
        await self._say(
            f"Explored {len(snapshots)} page(s) ({titles}): {total} interactive elements, "
            f"{a11y_count} accessibility observation(s)."
        )
        return snapshots

    async def _present_review(
        self,
        session: DesignSession,
        collection: TestCaseCollection,
        diff_summary: Optional[str],
        revised: bool,
    ) -> None:
        store, sm = session.store, session.sm
        review = ReviewManager(store)
        coverage = build_coverage(collection, session.criteria)
        if revised and session.collection:
            diff = review.record_revision(session.collection.version, collection)
            diff_summary = diff.generate_summary()
            store.write_json_atomic("coverage_matrix.json", coverage.model_dump())
        else:
            review.save_version(collection, coverage)
        session.collection = collection

        if sm.state.current_stage != Stage.STAGE_5_REVIEW_LOOP:
            await sm.advance_to(Stage.STAGE_5_REVIEW_LOOP, "Awaiting test case approval (Gate 1)")
        await self._card(
            "review_card",
            store.run_id,
            {
                "module": session.module,
                "version": collection.version,
                "sha256_hash": collection.compute_sha256_hash(),
                "can_revise": session.designer is not None,
                "diff_summary": diff_summary,
                "coverage": [i.model_dump() for i in coverage.items],
                "coverage_percentage": coverage.coverage_percentage,
                "required_secrets": required_secrets(collection),
                "unverified_locators": unverified_locators(collection, session.snapshots)[:15],
                "testcases_md": str(store.run_dir / "testcases" / f"v{collection.version}.md"),
                "testcases": [
                    {
                        "tc_id": tc.tc_id,
                        "title": tc.title,
                        "priority": tc.priority.value,
                        "category": tc.category.value,
                        "ac_ref": tc.ac_ref,
                        "test_types": tc.test_types,
                        "steps": tc.steps,
                        "expected_result": tc.expected_result,
                        "actions": [describe_action(a) for a in tc.actions],
                    }
                    for tc in collection.testcases
                ],
            },
        )

    async def handle_testcases_revise(self, params: Dict[str, Any]) -> Dict[str, Any]:
        session = self._require_session()
        approver = _require_approver(params)
        comments = str(params.get("comments") or "").strip()
        if not comments:
            raise ValueError("Describe the changes you want.")
        if not session.designer or not session.collection:
            raise RuntimeError("Revisions need an AI provider and a drafted suite.")
        if session.sm.state.current_stage != Stage.STAGE_5_REVIEW_LOOP:
            raise RuntimeError("Test cases are not awaiting review.")
        session.store.audit.log_event(
            stage=Stage.STAGE_5_REVIEW_LOOP.value,
            event_type="REVISION_REQUESTED",
            actor=approver,
            details={"version": session.collection.version, "comments": comments[:2000]},
        )
        self._start_background(self._revise(session, comments))
        return {"status": "revising"}

    async def _revise(self, session: DesignSession, comments: str) -> None:
        assert session.designer and session.collection
        await self._say("Revising test cases with the AI provider ...")
        current = session.collection
        result = await session.designer.revise(
            current, comments, session.requirement, session.criteria, session.snapshots
        )
        revised = build_collection(
            result,
            session.module,
            f"REQ-{module_code(session.module)}",
            version=current.version + 1,
            existing_ids={tc.tc_id for tc in current.testcases},
        )
        await self._present_review(session, revised, diff_summary=None, revised=True)

    async def handle_testcases_approve(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Gate 1: approve the exact drafted version (hash-bound), then generate and execute."""
        session = self._require_session()
        approver = _require_approver(params)
        collection = session.collection
        if not collection:
            raise RuntimeError("There are no drafted test cases to approve.")
        version = int(params.get("version", collection.version))
        sha256_hash = str(params.get("sha256_hash", ""))
        if version != collection.version or sha256_hash != collection.compute_sha256_hash():
            raise ValueError("Approval does not match the latest drafted test cases.")
        await session.sm.approve_testcases(version, approver, sha256_hash)
        self._start_background(self._build_and_run_new_suite(session, approver))
        return {"status": "approved", "stage": session.sm.state.current_stage.value}

    async def _build_and_run_new_suite(self, session: DesignSession, approver: str) -> None:
        store, sm = session.store, session.sm
        collection = session.collection
        assert collection is not None
        scope = store.load_scope()

        scripts_dir = store.run_dir / "scripts"
        paths = ScriptGenerator.write_scripts(scripts_dir, collection.testcases, session.module)
        result = ScriptValidator.validate_script(
            paths["test"].read_text(encoding="utf-8"),
            approved_tc_ids={tc.tc_id for tc in collection.testcases},
        )
        if not result.is_valid:
            raise RuntimeError(f"AST security gate rejected generated tests: {result.errors}")

        suites = SuiteStore(store.workspace_root)
        if suites.exists(session.slug):
            record = suites.load(session.slug)
            record.start_url, record.allowed_domains = scope.start_url, scope.allowed_domains
            record.environment, record.design_mode = scope.environment, session.design_mode
        else:
            record = SuiteRecord(
                slug=session.slug,
                module=session.module,
                start_url=scope.start_url,
                allowed_domains=scope.allowed_domains,
                environment=scope.environment,
                design_mode=session.design_mode,
            )
        record.requirement_text = session.requirement
        needed = required_secrets(collection)
        secrets = await self.secret_resolver(record, needed) if needed else {}

        if session.options.get("dry_run", True):
            proceed = await self._dry_run_gate(session, collection, scope, secrets, approver)
            if not proceed:
                return

        approval = suites.save_version(
            record,
            collection,
            scripts_dir,
            approver,
            store.read_text("requirement.md"),
            session.criteria,
            needed,
        )
        await self._say(
            f"Generated {len(collection.testcases)} pytest test(s), AST security gate passed. "
            f"Saved suite **{record.module}** v{approval.version} to the library."
        )
        await self._execute_suite(
            store=store,
            sm=sm,
            record=record,
            collection=collection,
            tests_dir=paths["test"].parent,
            options=session.options,
            run_type="update" if session.base_collection else "initial",
            actor=approver,
            secrets=secrets,
        )
        self.session = None

    async def _dry_run_gate(
        self,
        session: DesignSession,
        collection: TestCaseCollection,
        scope: ScopeModel,
        secrets: Dict[str, str],
        approver: str,
    ) -> bool:
        """Stage 7: replay every case once. Returns False when the suite went back to review."""
        sm, options = session.sm, session.options
        headed = options["headed"]
        await sm.advance_to(
            Stage.STAGE_7_DRY_RUN,
            f"Dry run: checking {len(collection.testcases)} case(s) step by step",
        )

        async def on_case(result: DryRunCaseResult) -> None:
            mark = {"ok": "ok", "issue": "PROBLEM", "blocked": "blocked (missing secret)"}
            note = f" - step {result.issue.step}: {result.issue.detail}" if result.issue else ""
            await self._log(f"{result.tc_id}: {mark[result.status]}{note}")

        report, failure_pages = await run_dry_run(
            collection,
            scope.start_url,
            scope.allowed_domains,
            secrets,
            headless=not headed,
            channel=self._browser_channel(options),
            slowmo_ms=options["slowmo_ms"] if headed else 0,
            evidence_dir=session.store.run_dir / "evidence" / "dry_run",
            on_case=on_case,
        )
        await self._end_log()
        session.store.write_json_atomic(
            "dry_run.json", {**report.model_dump(), "issues": len(report.issues)}
        )
        session.store.audit.log_event(
            stage=Stage.STAGE_7_DRY_RUN.value,
            event_type="DRY_RUN_COMPLETED",
            actor="engine",
            details={"cases": len(report.cases), "issues": len(report.issues)},
        )
        if not report.issues:
            await self._say(
                f"Dry run passed: every step of {len(report.cases)} case(s) is executable"
                f" ({report.duration_seconds}s)."
            )
            return True

        session.dry_run_report = report
        session.pending_dry_run = asyncio.get_running_loop().create_future()
        await self._card(
            "dry_run_card",
            session.store.run_id,
            {
                "module": session.module,
                "issues": [i.model_dump() for i in report.issues],
                "cases": [c.model_dump() for c in report.cases],
                "can_fix": session.designer is not None,
            },
        )
        decision: str = await session.pending_dry_run
        session.pending_dry_run = None
        session.store.audit.log_event(
            stage=Stage.STAGE_7_DRY_RUN.value,
            event_type="DRY_RUN_DECISION",
            actor=approver,
            details={"decision": decision, "issues": len(report.issues)},
        )
        if decision == "run":
            await self._say("Running the suite as approved despite the dry-run problems.")
            return True
        if decision == "cancel":
            await sm.cancel("Cancelled after dry run", actor=approver)
            self.session = None
            return False
        session.snapshots = list(session.snapshots) + failure_pages
        await sm.reopen_review(approver, report.revision_comments())
        await self._revise(session, report.revision_comments())
        return False

    async def handle_dry_run_decide(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Decision after a dry run found problems: 'fix' (AI revision), 'run', or 'cancel'."""
        session = self._require_session()
        _require_approver(params)
        if not session.pending_dry_run or session.pending_dry_run.done():
            raise RuntimeError("No dry-run decision is pending.")
        decision = str(params.get("decision") or "")
        if decision not in ("fix", "run", "cancel"):
            raise ValueError("Decision must be 'fix', 'run', or 'cancel'.")
        if decision == "fix" and not session.designer:
            raise ValueError("Repairing test cases needs a connected AI provider.")
        session.pending_dry_run.set_result(decision)
        return {"status": decision}

    # ------------------------------------------------------------------ execution (shared)

    async def _execute_suite(
        self,
        store: RunStore,
        sm: OrchestrationStateMachine,
        record: SuiteRecord,
        collection: TestCaseCollection,
        tests_dir: Path,
        options: Dict[str, Any],
        run_type: str,
        actor: str,
        select_tc_ids: Optional[List[str]] = None,
        marker: Optional[str] = None,
        regression_id: Optional[str] = None,
        show_card: bool = True,
        secrets: Optional[Dict[str, str]] = None,
        origin_map: Optional[Dict[str, str]] = None,
    ) -> SuiteRunSummary:
        scope = store.load_scope()
        selected = [
            tc for tc in collection.testcases if not select_tc_ids or tc.tc_id in select_tc_ids
        ]
        if secrets is None:
            secrets = {}
            if record.required_secrets:
                secrets = await self.secret_resolver(record, record.required_secrets)

        headed = options["headed"]
        channel = self._browser_channel(options)
        await sm.advance_to(
            Stage.STAGE_8_EXECUTION,
            f"Running {len(selected)} test(s) of {record.module} in "
            f"{'visible' if headed else 'headless'} {'Google Chrome' if channel else 'Chromium'}",
        )
        loop = asyncio.get_running_loop()
        pending: List[Future] = []

        def on_output(line: str) -> None:
            pending.append(asyncio.run_coroutine_threadsafe(self._log(line), loop))

        runner = PytestRunner(store)
        summary: ExecutionSummary = await loop.run_in_executor(
            None,
            functools.partial(
                runner.run_tests,
                test_dir=tests_dir,
                base_url=scope.start_url,
                retries=1,
                timeout_seconds=max(600, 120 * len(selected)),
                headed=headed,
                browser_channel=channel,
                slowmo_ms=options["slowmo_ms"] if headed else 0,
                on_output=on_output,
                allowed_domains=scope.allowed_domains,
                secrets=secrets,
                select_tests=[test_function_name(t) for t in select_tc_ids or []] or None,
                marker=marker,
                origin_map=origin_map,
            ),
        )
        if pending:
            await asyncio.gather(*(asyncio.wrap_future(f) for f in pending))
        await self._end_log()

        await sm.advance_to(Stage.STAGE_9_INVESTIGATION, "Indexing evidence and investigating")
        evidence_index = EvidenceIndex()
        evidence_index.scan_run_directory(store.run_dir)
        evidence_index.save(store.run_dir / "evidence" / "evidence_index.json")
        classifier = FailureClassifier(
            evidence_index=evidence_index, llm=self.llm if options["ai_enabled"] else None
        )
        tc_map = {tc.tc_id: tc for tc in collection.testcases}
        investigations = []
        for outcome in summary.outcomes:
            if outcome.status in ("failed", "flaky"):
                tc = tc_map.get(outcome.tc_id)
                investigations.append(
                    await classifier.investigate_async(outcome, tc.ac_ref if tc else None)
                )

        await sm.advance_to(Stage.STAGE_10_SIGN_OFF, "Building reports")
        builder = ReportBuilder()
        payload = builder.prepare_payload(
            run_id=store.run_id,
            target_url=scope.start_url,
            summary=summary,
            test_collection=collection,
            investigations=investigations,
            gate_1_hash=sm.state.approved_testcases_hash,
            audit_count=store.audit.current_entry_id,
            audit_hash_head=store.audit.last_hash,
            module=record.module,
            run_type=run_type,
            environment=scope.environment,
            triggered_by=actor,
        )
        reports = builder.write_all_reports(payload, store)

        statuses = {o.tc_id: o.status for o in summary.outcomes}
        run_summary = SuiteRunSummary(
            run_id=store.run_id,
            run_type=run_type,
            triggered_by=actor,
            version=record.current_version,
            total=summary.total_tests,
            passed=summary.passed,
            failed=summary.failed,
            flaky=summary.flaky,
            blocked=summary.blocked,
            skipped=summary.skipped,
            duration_seconds=round(summary.duration_seconds, 1),
            failed_tc_ids=sorted(t for t, s in statuses.items() if s in ("failed", "blocked")),
            report_html=str(reports["html"]),
            regression_id=regression_id,
            environment=scope.environment,
            target_url=scope.start_url,
        )
        SuiteStore(store.workspace_root).record_run(record.slug, run_summary, statuses)

        if show_card:
            await self._card(
                "report_card",
                store.run_id,
                {
                    **run_summary.model_dump(),
                    "module": record.module,
                    "slug": record.slug,
                    "duration_seconds": run_summary.duration_seconds,
                    "run_dir": str(store.run_dir),
                },
            )
        await sm.advance_to(Stage.COMPLETED, f"{record.module}: {run_type} finished")
        return run_summary

    def _prepare_stored_run(
        self, workspace_root: str, record: SuiteRecord, run_id: str
    ) -> Tuple[RunStore, OrchestrationStateMachine, TestCaseCollection, Path, SuiteApproval]:
        suites = SuiteStore(workspace_root)
        approval = suites.verify_integrity(record.slug)
        store = RunStore(workspace_root=workspace_root, run_id=run_id)
        sm = OrchestrationStateMachine(run_store=store, notify_callback=self._notify)
        collection = suites.load_version(record.slug)
        store.write_json_atomic(
            f"testcases/v{collection.version}.json", collection.model_dump(mode="json")
        )
        tests_dir = suites.materialize_scripts(record.slug, store.run_dir / "scripts")
        return store, sm, collection, tests_dir, approval

    @staticmethod
    def _resolve_target(
        record: SuiteRecord, environment: Optional[str], base_url: Optional[str] = None
    ) -> Tuple[ScopeModel, Dict[str, str]]:
        """Scope for re-running a stored suite against its default or another environment.

        Returns the scope and the origin map that moves the approved suite's URLs to the
        chosen environment at run time (the approved scripts themselves never change).
        """
        env = (environment or "").strip() or record.environment
        url = (base_url or "").strip()
        if not url:
            if env in record.environments:
                url = record.environments[env]
            elif env == record.environment:
                url = record.start_url
            else:
                raise ValueError(
                    f"'{record.module}' has no URL for environment '{env}'. "
                    "Add it with the environment's start URL first."
                )
        if urlparse(url).scheme not in ("http", "https"):
            raise ValueError("Environment URL must start with https:// or http://.")
        original_host = (urlparse(record.start_url).hostname or "").lower()
        new_host = (urlparse(url).hostname or "").lower()
        domains = [new_host if d == original_host else d for d in record.allowed_domains]
        if new_host and new_host not in domains:
            domains.insert(0, new_host)
        ok, reason = validate_destination_url(url, domains, resolve_dns=True)
        if not ok:
            raise ValueError(f"Environment '{env}' rejected by network policy: {reason}")
        scope = ScopeModel(
            start_url=url,
            allowed_domains=domains,
            environment=env,
            authorized_attestation=True,
        )
        origin_map = {}
        if _origin(url) != _origin(record.start_url):
            origin_map[_origin(record.start_url)] = _origin(url)
        return scope, origin_map

    # ------------------------------------------------------------------ library: list/retest

    async def handle_suites_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        suites = SuiteStore(params.get("workspace_root") or str(Path.cwd()))
        items = []
        for record in suites.list():
            latest = suites.latest_results(record.slug)
            items.append(
                {
                    **record.model_dump(),
                    "failed_count": sum(1 for s in latest.values() if s in ("failed", "blocked")),
                    "testcases_md": str(
                        suites.suite_dir(record.slug)
                        / "versions"
                        / f"v{record.current_version}"
                        / "testcases.md"
                    ),
                }
            )
        return {"suites": items}

    async def handle_suite_get(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Stored requirement, criteria, and scope of one suite (to prefill an update)."""
        suites = SuiteStore(params.get("workspace_root") or str(Path.cwd()))
        record = suites.load(str(params.get("slug", "")))
        criteria = suites.criteria(record.slug)
        return {
            **record.model_dump(),
            "acceptance_criteria": "\n".join(c.get("text", "") for c in criteria),
            "extra_domains": [
                d
                for d in record.allowed_domains
                if d != (urlparse(record.start_url).hostname or "").lower()
            ],
        }

    async def handle_suite_delete(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Remove a suite from the library; its files are archived, not destroyed."""
        approver = _require_approver(params)
        if self._task and not self._task.done():
            raise RuntimeError("Wait for the current run to finish before deleting a suite.")
        suites = SuiteStore(params.get("workspace_root") or str(Path.cwd()))
        record = suites.load(str(params.get("slug", "")))
        if self.session and self.session.slug == record.slug:
            raise RuntimeError(f"'{record.module}' is being updated; finish or cancel that first.")
        target = suites.archive(record.slug, approver)
        return {"status": "archived", "module": record.module, "archived_to": str(target)}

    async def handle_suite_retest(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Retesting: re-run every case of one module (or only those that failed last time)."""
        approver = _require_approver(params)
        if not params.get("authorized_attestation"):
            raise ValueError("Confirm you are authorized to test this target before retesting.")
        workspace_root = params.get("workspace_root") or str(Path.cwd())
        suites = SuiteStore(workspace_root)
        record = suites.load(str(params.get("slug", "")))
        failed_only = bool(params.get("failed_only"))
        select = None
        if failed_only:
            latest = suites.latest_results(record.slug)
            select = sorted(t for t, s in latest.items() if s in ("failed", "blocked", "flaky"))
            if not select:
                raise ValueError(f"'{record.module}' has no failed cases to retest.")
        run_type = "retest-failed" if failed_only else "retest"
        run_id = f"{run_type}-{record.slug}-{_stamp()}"
        options = self._options(params)
        base_url = str(params.get("base_url") or "").strip()
        scope, origin_map = self._resolve_target(record, params.get("environment"), base_url)
        if base_url and record.environments.get(scope.environment) != base_url:
            record.environments[scope.environment] = base_url
            suites.save_record(record)
        self._start_background(
            self._retest(
                workspace_root,
                record,
                run_id,
                run_type,
                options,
                approver,
                select,
                scope,
                origin_map,
            )
        )
        return {
            "status": "started",
            "run_id": run_id,
            "selected": select,
            "environment": scope.environment,
            "target_url": scope.start_url,
        }

    async def _retest(
        self,
        workspace_root: str,
        record: SuiteRecord,
        run_id: str,
        run_type: str,
        options: Dict[str, Any],
        actor: str,
        select: Optional[List[str]],
        scope: ScopeModel,
        origin_map: Dict[str, str],
    ) -> None:
        store, sm, collection, tests_dir, approval = self._prepare_stored_run(
            workspace_root, record, run_id
        )
        self.run_store, self.state_machine = store, sm
        await sm.restore_approved_suite(
            scope, approval.version, approval.sha256_hash, approval.approver, actor
        )
        scope_note = f"{len(select)} failed case(s)" if select else "all cases"
        await self._say(
            f"Retesting **{record.module}** v{approval.version}: {scope_note} on "
            f"**{scope.environment}** ({scope.start_url})."
        )
        await self._execute_suite(
            store,
            sm,
            record,
            collection,
            tests_dir,
            options,
            run_type,
            actor,
            select_tc_ids=select,
            origin_map=origin_map,
        )

    # ------------------------------------------------------------------ regression

    async def handle_regression_run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Regression: run every stored suite (optionally only cases tagged with a test type)."""
        approver = _require_approver(params)
        if not params.get("authorized_attestation"):
            raise ValueError("Confirm you are authorized to test these targets before regression.")
        workspace_root = params.get("workspace_root") or str(Path.cwd())
        records = SuiteStore(workspace_root).list()
        wanted = set(params.get("slugs") or [])
        if wanted:
            records = [r for r in records if r.slug in wanted]
        tag = (params.get("tag") or "").strip().lower() or None
        if tag:
            if tag not in TEST_TYPES:
                raise ValueError(f"Unknown test type '{tag}'. Use one of: {', '.join(TEST_TYPES)}.")
            records = [r for r in records if tag in r.test_types]
        if not records:
            raise ValueError(
                f"No suites contain '{tag}' cases." if tag else "No suites yet. Create one first."
            )
        regression_id = f"regression-{_stamp()}"
        self._start_background(
            self._regression(
                workspace_root,
                records,
                regression_id,
                tag,
                self._options(params),
                approver,
                params.get("environment"),
            )
        )
        return {"status": "started", "regression_id": regression_id, "suites": len(records)}

    async def _regression(
        self,
        workspace_root: str,
        records: List[SuiteRecord],
        regression_id: str,
        tag: Optional[str],
        options: Dict[str, Any],
        actor: str,
        environment: Optional[str],
    ) -> None:
        report = RegressionReport(
            regression_id=regression_id,
            triggered_by=actor,
            tag=tag,
            environment=(environment or "").strip() or None,
        )
        suites = SuiteStore(workspace_root)
        await self._say(
            f"Regression **{regression_id}**: {len(records)} suite(s)"
            + (f", only '{tag}' cases" if tag else "")
            + "."
        )
        for index, record in enumerate(records, start=1):
            await self._say(f"[{index}/{len(records)}] Running suite **{record.module}** ...")
            previous = suites.latest_results(record.slug)
            try:
                scope, origin_map = self._resolve_target(record, environment)
                store, sm, collection, tests_dir, approval = self._prepare_stored_run(
                    workspace_root, record, f"{regression_id}-{record.slug}"
                )
                self.run_store, self.state_machine = store, sm
                await sm.restore_approved_suite(
                    scope, approval.version, approval.sha256_hash, approval.approver, actor
                )
                summary = await self._execute_suite(
                    store,
                    sm,
                    record,
                    collection,
                    tests_dir,
                    options,
                    "regression",
                    actor,
                    marker=tag,
                    regression_id=regression_id,
                    show_card=False,
                    origin_map=origin_map,
                )
                current = suites.latest_results(record.slug)
                delta = compare_statuses(previous, current)
                report.suites.append(
                    RegressionSuiteResult(
                        slug=record.slug,
                        module=record.module,
                        version=approval.version,
                        status="failed" if summary.failed else "passed",
                        total=summary.total,
                        passed=summary.passed,
                        failed=summary.failed,
                        flaky=summary.flaky,
                        blocked=summary.blocked,
                        skipped=summary.skipped,
                        duration_seconds=summary.duration_seconds,
                        newly_failing=delta["newly_failing"],
                        fixed=delta["fixed"],
                        report_html=summary.report_html,
                    )
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - includes SuiteIntegrityError
                logger.exception("Regression suite %s failed", record.slug)
                await self._end_log()
                await self._say(f"Suite **{record.module}** could not run: {exc}")
                report.suites.append(
                    RegressionSuiteResult(
                        slug=record.slug,
                        module=record.module,
                        version=record.current_version,
                        status="error",
                        error=str(exc)[:500],
                    )
                )

        paths = write_regression_report(Path(workspace_root), report)
        await self._card(
            "regression_card",
            regression_id,
            {
                "regression_id": regression_id,
                "tag": tag,
                "environment": report.environment,
                "totals": report.totals,
                "suites": [s.model_dump() for s in report.suites],
                "report_html": str(paths["html"]),
            },
        )

    # ------------------------------------------------------------------ misc handlers

    async def handle_defect_signoff(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Gate 2 Defect Sign-off."""
        if not self.state_machine:
            raise RuntimeError("Engine not initialized with an active run.")
        approver = _require_approver(params)
        failure_id = params.get("failure_id", "")
        await self.state_machine.sign_off_gate_2(
            failure_id=failure_id,
            approver=approver,
            defect_confirmed=params.get("defect_confirmed", True),
            notes=params.get("notes"),
        )
        return {"status": "signed_off", "failure_id": failure_id}

    async def handle_run_cancel(self, params: Dict[str, Any]) -> Dict[str, Any]:
        reason = params.get("reason", "Cancelled by user")
        if self._task and not self._task.done():
            self._task.cancel()
        if self.session and self.session.pending_questions:
            self.session.pending_questions.cancel()
        if self.session and self.session.pending_dry_run:
            self.session.pending_dry_run.cancel()
        if self.state_machine and self.state_machine.state.current_stage not in (
            Stage.COMPLETED,
            Stage.CANCELLED,
        ):
            await self.state_machine.cancel(reason, actor=str(params.get("approver") or "user"))
        self.session = None
        return {"status": "cancelled"}

    async def handle_run_resume(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Re-open an existing run from disk after verifying its audit chain."""
        run_id = params.get("run_id")
        workspace_root = params.get("workspace_root", str(Path.cwd()))
        if not run_id:
            raise ValueError("run_id required to resume")
        self.run_store = RunStore(workspace_root=workspace_root, run_id=run_id)
        self.state_machine = OrchestrationStateMachine(
            run_store=self.run_store, notify_callback=self._notify
        )
        valid, err = self.run_store.audit.verify_log_file(self.run_store.run_dir / "audit.jsonl")
        if not valid:
            raise ValueError(f"Audit log verification failed: {err}")
        if (self.run_store.run_dir / "scope.json").exists():
            _ = self.run_store.load_scope()
            self.state_machine.state.scope_confirmed = True
        return {"status": "resumed", "run_id": run_id}

    # ------------------------------------------------------------------ main loop

    async def run(self) -> None:
        """Read messages from stdin: requests are dispatched, responses resolve our requests."""
        await self.channel.initialize()
        inflight: set = set()
        while True:
            line = await self.channel.read_line()
            if line is None:
                break
            if self._is_response(line):
                continue
            task = asyncio.create_task(self._dispatch(line))
            inflight.add(task)
            task.add_done_callback(inflight.discard)

    def _is_response(self, line: str) -> bool:
        try:
            message = json.loads(line)
        except ValueError:
            return False
        if isinstance(message, dict) and "method" not in message and "id" in message:
            if not self.channel.resolve_response(message):
                logger.warning("Dropped response for unknown request id %s", message.get("id"))
            return True
        return False

    async def _dispatch(self, line: str) -> None:
        response = await self.dispatcher.handle_payload(line)
        if response is not None:
            await self.channel.send_response(response)


def main():
    logging.basicConfig(level=os.environ.get("QA_ENGINE_LOG_LEVEL", "WARNING"))
    server = QAEngineServer()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
