"""Command-line runner for the QA harness (no VS Code required).

Examples:
    qa-harness suite --module "Login" --url https://your-app.example/login \
        --environment staging --requirement-file req.md --criteria-file ac.txt --approver you
    qa-harness smoke --url https://your-app.example --module "Home page" \
        --environment staging --approver your-github-name --yes
    qa-harness list
    qa-harness retest --module "Home page" --failed-only --approver you --yes
    qa-harness retest --module "Home page" --environment uat --base-url https://uat.your-app.example
    qa-harness regression --tag smoke --environment staging --approver you --yes

AI design ("suite") and AI failure investigation use the provider configured through
QA_AI_PROVIDER / QA_AI_API_KEY / QA_AI_MODEL (see qa_engine.llm.http_provider).
Suite secrets are read from environment variables named QA_SECRET_<NAME>.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from qa_engine.generation.testcases import TEST_TYPES
from qa_engine.llm.http_provider import HttpLLMProvider, LLMConfigError
from qa_engine.main import QAEngineServer
from qa_engine.orchestrator.rpc import RemoteRPCError, StdioChannel
from qa_engine.orchestrator.state_machine import Stage
from qa_engine.orchestrator.suite_store import SuiteRecord, SuiteStore, slugify


class ConsoleChannel(StdioChannel):
    """Prints engine notifications for a human instead of writing JSON-RPC to stdout."""

    def __init__(self):
        super().__init__()
        self.cards: Dict[str, Dict[str, Any]] = {}

    async def request(self, method: str, params=None, timeout: float = 300.0):
        raise RemoteRPCError(-32601, f"'{method}' is only available inside VS Code.")

    async def send_notification(self, method: str, params: Optional[Dict[str, Any]] = None):
        params = params or {}
        if method == "message.stream":
            chunk = params.get("chunk", "")
            if params.get("style") == "log":
                if chunk:
                    print(f"  | {chunk}", end="", flush=True)
                return
            if chunk:
                print(chunk.replace("**", ""), flush=True)
        elif method == "stage.update":
            print(f"[{params.get('stage')}] {params.get('description', '')}", flush=True)
        elif method == "card.show":
            self.cards[params.get("card_type", "")] = params.get("data") or {}
            _print_card(params.get("card_type", ""), params.get("data") or {})


def _print_card(card_type: str, data: Dict[str, Any]) -> None:
    if card_type == "review_card":
        print(f"\nDrafted {len(data.get('testcases', []))} test case(s) for {data.get('module')}:")
        if data.get("diff_summary"):
            print(f"  {data['diff_summary']}")
        for tc in data.get("testcases", []):
            ac = f" {tc['ac_ref']}" if tc.get("ac_ref") else ""
            print(f"  {tc['tc_id']}  [{tc['priority']}]{ac}  {tc['title']}")
        if data.get("required_secrets"):
            print(f"  Needs secrets: {', '.join(data['required_secrets'])}")
        print(f"  Cases file: {data.get('testcases_md')}\n")
    elif card_type == "clarification_card":
        print(f"\nAnalysis: {data.get('summary', '')}")
    elif card_type == "dry_run_card":
        print(f"\nDry run found {len(data.get('issues', []))} problem(s):")
        for issue in data.get("issues", []):
            print(f"  {issue['tc_id']} step {issue['step']} ({issue['action']}): {issue['detail']}")
    elif card_type == "report_card":
        print(
            f"\nResult: {data.get('passed')}/{data.get('total')} passed, "
            f"{data.get('failed')} failed, {data.get('flaky')} flaky, "
            f"{data.get('blocked')} blocked"
        )
        usage = data.get("ai_usage") or {}
        inv = usage.get("investigations") or {}
        if any(inv.values()):
            print(
                f"Failure analysis: {inv.get('ai', 0)} by AI, {inv.get('reused', 0)} reused, "
                f"{inv.get('cached', 0)} from earlier runs, {inv.get('rules', 0)} by rules, "
                f"{inv.get('limited', 0)} by rules (AI limit reached)"
            )
        print(f"Report: {data.get('report_html')}\n")
    elif card_type == "regression_card":
        totals = data.get("totals", {})
        print(
            f"\nRegression: {totals.get('passed')}/{totals.get('total')} passed across "
            f"{len(data.get('suites', []))} suite(s); {totals.get('failed')} failed"
        )
        for suite in data.get("suites", []):
            detail = suite.get("error") or f"{suite['passed']}/{suite['total']}"
            print(f"  {suite['module']}: {suite['status']} ({detail})")
        print(f"AI calls: {data.get('ai_calls', 0)}")
        print(f"Report: {data.get('report_html')}\n")


async def _env_secrets(record: SuiteRecord, names: List[str]) -> Dict[str, str]:
    found = {n: os.environ[f"QA_SECRET_{n}"] for n in names if os.environ.get(f"QA_SECRET_{n}")}
    missing = sorted(set(names) - set(found))
    if missing:
        print(f"Missing secrets (tests using them will be blocked): {', '.join(missing)}")
    return found


def _llm() -> Optional[HttpLLMProvider]:
    return HttpLLMProvider.from_env(os.environ)


def _server(channel: ConsoleChannel, llm: Optional[HttpLLMProvider]) -> QAEngineServer:
    return QAEngineServer(channel=channel, llm=llm, secret_resolver=_env_secrets)


def _options(args, ai_enabled: bool = False) -> Dict[str, Any]:
    return {
        "headed": not args.headless,
        "slowmo_ms": args.slowmo,
        "browser_channel": args.channel,
        "ai_enabled": ai_enabled,
        "dry_run": not getattr(args, "no_dry_run", False),
        "ai_investigation": args.ai_investigations > 0,
        "ai_max_investigations": args.ai_investigations,
        "ai_daily_investigation_limit": args.ai_daily_limit,
        "ai_reuse_analyses": not args.no_ai_reuse,
    }


def _confirm(args, prompt: str) -> bool:
    if args.yes:
        return True
    return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")


def _failed(server: QAEngineServer) -> bool:
    sm = server.state_machine
    return sm is None or sm.state.current_stage in (Stage.ERROR, Stage.CANCELLED)


def _exit_code(report: Optional[Dict[str, Any]]) -> int:
    if not report:
        return 2
    return 0 if not report.get("failed") else 3


def _read_text(value: Optional[str], path: Optional[str]) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    return value or ""


async def _next_pause(server: QAEngineServer) -> str:
    """Wait until the workflow needs input ('questions', 'dry_run') or is idle ('idle')."""
    while True:
        session = server.session
        if session and session.pending_questions and not session.pending_questions.done():
            return "questions"
        if session and session.pending_dry_run and not session.pending_dry_run.done():
            return "dry_run"
        task = server._task
        if task is None or task.done():
            return "idle"
        await asyncio.sleep(0.2)


async def _drive_design(server: QAEngineServer, channel: ConsoleChannel, args, module: str) -> int:
    """Answer clarifications, review/revise/approve, and handle the dry run until a report."""
    while True:
        pause = await _next_pause(server)
        session = server.session
        if pause == "questions" and session:
            card = channel.cards.get("clarification_card", {})
            answers = {}
            for q in card.get("questions", []):
                prompt = f"Q: {q.get('question_text')}\n   answer (Enter to skip): "
                answers[q.get("question_id", "")] = "" if args.yes else input(prompt).strip()
            await server.handle_clarifications_answer(
                {"approver": args.approver, "answers": answers}
            )
            continue
        if pause == "dry_run" and session:
            can_fix = bool(channel.cards.get("dry_run_card", {}).get("can_fix"))
            if args.yes:
                choice = "run"
            else:
                options = "[f]ix with AI, [r]un anyway, [c]ancel" if can_fix else "[r]un, [c]ancel"
                choice = {"f": "fix", "r": "run", "c": "cancel"}.get(
                    input(f"Dry run problems found. {options}: ").strip().lower()[:1], "cancel"
                )
                if choice == "fix" and not can_fix:
                    choice = "cancel"
            await server.handle_dry_run_decide({"approver": args.approver, "decision": choice})
            continue

        sm = server.state_machine
        if sm is not None and sm.state.current_stage == Stage.CANCELLED:
            return 1
        if _failed(server):
            return 2
        session = server.session
        if session is None:
            return _exit_code(channel.cards.get("report_card"))
        if not session.collection or session.sm.state.current_stage != Stage.STAGE_5_REVIEW_LOOP:
            return 2
        if args.yes:
            decision = "a"
        else:
            options = (
                "[a]pprove and run, [r]equest changes, [q]uit"
                if session.designer
                else ("[a]pprove and run, [q]uit")
            )
            decision = input(f"Review the cases for {module}. {options}: ").strip().lower()[:1]
        if decision == "r" and session.designer:
            comments = input("Describe the changes: ").strip()
            if comments:
                await server.handle_testcases_revise(
                    {"approver": args.approver, "comments": comments}
                )
            continue
        if decision != "a":
            return 1
        await server.handle_testcases_approve(
            {
                "approver": args.approver,
                "version": session.collection.version,
                "sha256_hash": session.collection.compute_sha256_hash(),
            }
        )


async def _start_design(
    server, channel, args, design_mode: str, extra: Dict[str, Any], ai: bool
) -> int:
    domains = [d.strip() for d in (args.domains or "").split(",") if d.strip()]
    started = await server.handle_run_start(
        {
            "workspace_root": args.workspace,
            "start_url": args.url,
            "module": args.module or "",
            "allowed_domains": domains,
            "environment": args.environment,
            "design_mode": design_mode,
            "approver": args.approver,
            **extra,
            **_options(args, ai_enabled=ai),
        }
    )
    scope_data = channel.cards.get("scope_card", {})
    if scope_data.get("updates_existing_suite"):
        print(f"'{started['module']}' already exists: this creates its next version.")
    print(f"Target: {scope_data.get('start_url')}  domains: {scope_data.get('allowed_domains')}")
    if not _confirm(args, "I am authorized to test this target. Continue?"):
        return 1
    await server.handle_scope_confirm(
        {
            "approver": args.approver,
            "scope": {
                "start_url": scope_data["start_url"],
                "allowed_domains": scope_data["allowed_domains"],
                "environment": args.environment,
                "authorized_attestation": True,
            },
        }
    )
    return await _drive_design(server, channel, args, started["module"])


async def cmd_suite(args) -> int:
    llm = _llm()
    if llm is None:
        raise LLMConfigError(
            "Requirement-driven design needs an AI provider: set QA_AI_PROVIDER, QA_AI_API_KEY "
            "and QA_AI_MODEL (or use the VS Code panel with GitHub Copilot)."
        )
    criteria = _read_text(args.criteria, args.criteria_file).strip()
    if not criteria:
        raise ValueError("Give acceptance criteria with --criteria or --criteria-file.")
    channel = ConsoleChannel()
    server = _server(channel, llm)
    extra = {
        "requirement_text": _read_text(args.requirement, args.requirement_file),
        "acceptance_criteria": criteria,
    }
    return await _start_design(server, channel, args, "ai", extra, ai=True)


async def cmd_smoke(args) -> int:
    channel = ConsoleChannel()
    llm = _llm()
    server = _server(channel, llm)
    return await _start_design(server, channel, args, "smoke", {}, ai=llm is not None)


async def cmd_list(args) -> int:
    records = SuiteStore(args.workspace).list()
    if not records:
        print("No suites yet. Create one with the 'suite' or 'smoke' command, or from VS Code.")
        return 0
    for r in records:
        last = r.last_run
        status = (
            f"last {last.run_type}: {last.passed}/{last.total} passed ({last.started_at[:19]})"
            if last
            else "never run"
        )
        envs = ", ".join([f"{r.environment} (default)", *r.environments.keys()])
        print(f"{r.module}  [{r.slug}]  v{r.current_version}  {r.total_cases} case(s)  {status}")
        print(f"    environments: {envs}")
    return 0


async def cmd_retest(args) -> int:
    channel = ConsoleChannel()
    llm = _llm()
    server = _server(channel, llm)
    if not _confirm(args, f"I am authorized to test the target of '{args.module}'. Continue?"):
        return 1
    await server.handle_suite_retest(
        {
            "workspace_root": args.workspace,
            "slug": slugify(args.module),
            "failed_only": args.failed_only,
            "approver": args.approver,
            "authorized_attestation": True,
            "environment": args.environment,
            "base_url": args.base_url,
            **_options(args, ai_enabled=llm is not None),
        }
    )
    await server.wait_idle()
    return 2 if _failed(server) else _exit_code(channel.cards.get("report_card"))


async def cmd_regression(args) -> int:
    channel = ConsoleChannel()
    llm = _llm()
    server = _server(channel, llm)
    if not _confirm(args, "I am authorized to test every suite target. Continue?"):
        return 1
    await server.handle_regression_run(
        {
            "workspace_root": args.workspace,
            "tag": args.tag,
            "approver": args.approver,
            "authorized_attestation": True,
            "environment": args.environment,
            **_options(args, ai_enabled=llm is not None),
        }
    )
    await server.wait_idle()
    card = channel.cards.get("regression_card")
    if not card:
        return 2
    totals = card["totals"]
    errors = any(s.get("status") == "error" for s in card.get("suites", []))
    return 3 if totals.get("failed") or errors else 0


async def cmd_delete(args) -> int:
    channel = ConsoleChannel()
    server = _server(channel, None)
    if not _confirm(args, f"Remove '{args.module}' from the suite library (archived, not erased)?"):
        return 1
    result = await server.handle_suite_delete(
        {"workspace_root": args.workspace, "slug": slugify(args.module), "approver": args.approver}
    )
    print(f"Archived {result['module']} to {result['archived_to']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qa-harness", description=__doc__.split("\n")[0])
    parser.add_argument(
        "--workspace", default=os.getcwd(), help="Folder that holds .qa-harness/ (default: cwd)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def approver_flag(p):
        p.add_argument(
            "--approver",
            default=os.environ.get("QA_APPROVER"),
            required=not os.environ.get("QA_APPROVER"),
            help="Your GitHub account name (or set QA_APPROVER)",
        )
        p.add_argument("--yes", action="store_true", help="Skip confirmation prompts")

    def run_flags(p):
        approver_flag(p)
        p.add_argument("--headless", action="store_true", help="Hide the browser")
        p.add_argument("--slowmo", type=int, default=300, help="Delay per action in ms (headed)")
        p.add_argument("--channel", default="chrome", help="chrome, msedge, or '' for Chromium")
        p.add_argument(
            "--ai-investigations",
            type=int,
            default=5,
            help="Max failures analyzed by AI per run (0 = rules only; default 5)",
        )
        p.add_argument(
            "--ai-daily-limit",
            type=int,
            default=50,
            help="Max AI failure analyses per day in this workspace (default 50)",
        )
        p.add_argument(
            "--no-ai-reuse",
            action="store_true",
            help="Always ask the AI, even for a failure analyzed in an earlier run",
        )

    def design_flags(p):
        p.add_argument("--url", required=True, help="Start URL of the module")
        p.add_argument("--module", help="Suite/module name (default: '<host> smoke')")
        p.add_argument("--domains", help="Extra allowed domains, comma separated")
        p.add_argument("--environment", required=True, help="e.g. dev, test, staging")
        p.add_argument(
            "--no-dry-run", action="store_true", help="Skip the Stage 7 dry run (not advised)"
        )
        run_flags(p)

    suite = sub.add_parser(
        "suite", help="Design a suite from a requirement + acceptance criteria with AI, then run"
    )
    design_flags(suite)
    suite.add_argument("--requirement", help="Requirement / user story text")
    suite.add_argument("--requirement-file", help="File containing the requirement")
    suite.add_argument("--criteria", help="Acceptance criteria, one per line")
    suite.add_argument("--criteria-file", help="File with one acceptance criterion per line")

    smoke = sub.add_parser("smoke", help="Explore a URL, design a smoke suite, approve, and run")
    design_flags(smoke)

    sub.add_parser("list", help="List stored suites and their environments")

    retest = sub.add_parser("retest", help="Re-run all cases (or only failed) of one module")
    retest.add_argument("--module", required=True)
    retest.add_argument("--failed-only", action="store_true")
    retest.add_argument("--environment", help="Environment name (default: the suite's own)")
    retest.add_argument("--base-url", help="Start URL for --environment (saved on the suite)")
    run_flags(retest)

    regression = sub.add_parser("regression", help="Run every stored suite")
    regression.add_argument("--tag", choices=TEST_TYPES, help="Only cases of this test type")
    regression.add_argument("--environment", help="Run each suite on this named environment")
    run_flags(regression)

    delete = sub.add_parser("delete", help="Remove a suite from the library (archived)")
    delete.add_argument("--module", required=True)
    approver_flag(delete)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    args.workspace = str(Path(args.workspace).resolve())
    commands = {
        "suite": cmd_suite,
        "smoke": cmd_smoke,
        "list": cmd_list,
        "retest": cmd_retest,
        "regression": cmd_regression,
        "delete": cmd_delete,
    }
    try:
        return asyncio.run(commands[args.command](args))
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
