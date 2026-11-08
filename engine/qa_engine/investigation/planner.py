"""Cost-aware failure investigation.

Order of preference for every failed or flaky outcome (cheapest first):

1. Deterministic rules (flaky retries, HTTP 5xx / connection errors): no AI.
2. Same specific error already analyzed by AI earlier in this run: reuse that analysis.
3. Same test, same normalized error, same approved suite and target in an earlier run (within
   the cache TTL): reuse that analysis.
4. AI analysis, while the per-run and daily limits allow it (highest priority cases first).
5. Otherwise the rule-based heuristic, with a note that the AI limit was reached.

Investigation only classifies failures: pass/fail results and Gate 2 (product defects always
need human sign-off) are identical whichever path is taken, and reused analyses cite only
evidence collected in the current run.
"""

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from qa_engine.execution.runner import TestCaseOutcome
from qa_engine.investigation.classifier import FailureClassifier
from qa_engine.investigation.schemas import InvestigationReport
from qa_engine.llm.usage import AIUsageLedger, write_json_atomic

# Errors shorter than this are too generic ("assert False") to share between tests.
MIN_SHARED_SIGNATURE_CHARS = 30
CACHE_MAX_ENTRIES = 500

# Only values that change between identical failures are removed (timings, addresses, uuids);
# other numbers stay, because "expected 3 items" and "expected 5 items" are different failures.
_NOISE = [
    (re.compile(r"0x[0-9a-fA-F]+"), "0x#"),
    (
        re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),
        "#uuid",
    ),
    (re.compile(r"\b\d+(\.\d+)?\s?(ms|s|sec|seconds|milliseconds)\b", re.I), "#ms"),
    (re.compile(r"\s+"), " "),
]


class InvestigationPolicy(BaseModel):
    ai_enabled: bool = True
    max_ai_per_run: int = Field(default=5, ge=0)
    daily_ai_limit: int = Field(default=50, ge=0)
    reuse_cached: bool = True
    cache_ttl_days: int = Field(default=7, ge=0)


def failure_signature(outcome: TestCaseOutcome) -> str:
    """The error with run-specific noise (timings, counts, ids) removed."""
    text = (outcome.error_message or "").strip()
    if not text:
        lines = [ln.strip() for ln in (outcome.stack_trace or "").splitlines() if ln.strip()]
        text = lines[-1] if lines else ""
    for pattern, repl in _NOISE:
        text = pattern.sub(repl, text)
    return text.strip()[:600]


class InvestigationCache:
    """AI analyses keyed by suite, approved version hash, target origin, test, and error."""

    def __init__(self, workspace_root: str, ttl_days: int = 7):
        self.path = Path(workspace_root) / ".qa-harness" / "cache" / "investigations.json"
        self.ttl = timedelta(days=ttl_days)

    @staticmethod
    def key(slug: str, suite_hash: str, origin: str, tc_id: str, signature: str) -> str:
        raw = "\n".join([slug, suite_hash or "", origin.lower(), tc_id, signature])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _load(self) -> Dict[str, Dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self, key: str) -> Optional[Dict]:
        entry = self._load().get(key)
        if not entry:
            return None
        try:
            created = datetime.fromisoformat(entry["created_at"])
        except (KeyError, ValueError):
            return None
        if datetime.now(timezone.utc) - created > self.ttl:
            return None
        return entry

    def put(self, key: str, report: InvestigationReport, run_id: str) -> None:
        data = self._load()
        data[key] = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "category": report.category.value,
            "confidence": report.confidence,
            "hypotheses": [h.model_dump() for h in report.hypotheses],
            "reproduction_steps": report.reproduction_steps,
            "recommended_action": report.recommended_action,
            "preventive_measure": report.preventive_measure,
        }
        if len(data) > CACHE_MAX_ENTRIES:
            newest = sorted(data.items(), key=lambda kv: kv[1].get("created_at", ""))
            data = dict(newest[-CACHE_MAX_ENTRIES:])
        try:
            write_json_atomic(self.path, data)
        except OSError:
            pass  # a missing cache entry only costs one AI call next time


async def investigate_failures(
    outcomes: List[TestCaseOutcome],
    classifier: FailureClassifier,
    policy: InvestigationPolicy,
    ledger: Optional[AIUsageLedger],
    cache: Optional[InvestigationCache],
    *,
    slug: str,
    suite_hash: str,
    origin: str,
    run_id: str,
    priorities: Optional[Dict[str, str]] = None,
    ac_refs: Optional[Dict[str, Optional[str]]] = None,
) -> Tuple[List[InvestigationReport], Dict[str, int]]:
    """Investigate failed/flaky outcomes; returns the reports and how each was produced."""
    priorities = priorities or {}
    ac_refs = ac_refs or {}
    stats = {"ai": 0, "reused": 0, "cached": 0, "rules": 0, "limited": 0}
    failing = [o for o in outcomes if o.status in ("failed", "flaky")]
    failing.sort(key=lambda o: (priorities.get(o.tc_id, "P9"), o.tc_id))

    reports: List[InvestigationReport] = []
    analyzed: Dict[str, InvestigationReport] = {}
    ai_calls = 0
    for outcome in failing:
        report = classifier.rule_based(outcome)
        if report:
            stats["rules"] += 1
            reports.append(report)
            continue

        signature = failure_signature(outcome)
        shared = len(signature) >= MIN_SHARED_SIGNATURE_CHARS
        key = InvestigationCache.key(slug, suite_hash, origin, outcome.tc_id, signature)
        cacheable = cache is not None and bool(signature)

        cached = cache.get(key) if (cacheable and policy.reuse_cached) else None
        if cached:
            report = classifier.reuse(
                outcome,
                cached,
                "cached",
                f"Same test, error, and approved suite as run {cached.get('run_id')}; "
                "its AI analysis is reused.",
            )
            reports.append(report)
            stats["cached"] += 1
            if shared:
                analyzed.setdefault(signature, report)
            continue

        if shared and signature in analyzed:
            first = analyzed[signature]
            report = classifier.reuse(
                outcome,
                first.model_dump(mode="json"),
                "reused",
                f"Same error as {first.failure_id} ({first.tc_id}); its AI analysis is reused.",
            )
            reports.append(report)
            stats["reused"] += 1
            if cacheable:
                cache.put(key, report, run_id)
            continue

        within_limits = (
            ai_calls < policy.max_ai_per_run
            and (ledger.today("investigation") if ledger else 0) < policy.daily_ai_limit
        )
        if classifier.llm and policy.ai_enabled and within_limits:
            ai_calls += 1
            report = await classifier.investigate_async(outcome, ac_refs.get(outcome.tc_id))
            if report.analysis_source == "ai":
                stats["ai"] += 1
                if shared:
                    analyzed[signature] = report
                if cacheable:
                    cache.put(key, report, run_id)
            else:
                stats["rules"] += 1
            reports.append(report)
            continue

        note = None
        if classifier.llm and policy.ai_enabled:
            note = (
                "AI analysis skipped: the per-run or daily AI limit was reached; "
                "classified by rules."
            )
            stats["limited"] += 1
        else:
            stats["rules"] += 1
        reports.append(classifier.investigate(outcome, note=note))
    return reports, stats
