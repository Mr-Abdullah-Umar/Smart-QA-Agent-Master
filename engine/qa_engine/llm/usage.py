"""AI usage metering: per-run counters and a per-day ledger in the workspace.

Every model call goes through `MeteredLLM`, which tags it with a purpose ("design" for
requirement analysis, page selection, design, revision, and dry-run repair; "investigation"
for failure root-cause analysis). Design calls are never limited, because a half-designed
suite is worse than the cost. Only investigation calls are capped (see `qa_engine.investigation.
planner`), and a capped investigation falls back to deterministic rules, so test results never
depend on the remaining budget.
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional

from qa_engine.llm.provider import LLMProvider, LLMResponse, ToolDefinition

logger = logging.getLogger(__name__)

PURPOSES = ("design", "investigation")
LEDGER_DAYS = 30


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _chars(messages: List[Dict[str, str]]) -> int:
    return sum(len(str(m.get("content", ""))) for m in messages)


def write_json_atomic(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class UsageCounter:
    """Calls and approximate tokens (characters / 4) per purpose for one run or session."""

    def __init__(self) -> None:
        self.calls: Dict[str, int] = dict.fromkeys(PURPOSES, 0)
        self.prompt_chars: Dict[str, int] = dict.fromkeys(PURPOSES, 0)
        self.reply_chars: Dict[str, int] = dict.fromkeys(PURPOSES, 0)

    def record(self, purpose: str, prompt_chars: int, reply_chars: int) -> None:
        self.calls[purpose] = self.calls.get(purpose, 0) + 1
        self.prompt_chars[purpose] = self.prompt_chars.get(purpose, 0) + prompt_chars
        self.reply_chars[purpose] = self.reply_chars.get(purpose, 0) + reply_chars

    @property
    def total_calls(self) -> int:
        return sum(self.calls.values())

    def to_dict(self) -> Dict[str, object]:
        tokens = {
            p: (self.prompt_chars.get(p, 0) + self.reply_chars.get(p, 0)) // 4 for p in self.calls
        }
        return {
            "calls": dict(self.calls),
            "total_calls": self.total_calls,
            "approx_tokens": tokens,
            "total_approx_tokens": sum(tokens.values()),
        }


class AIUsageLedger:
    """Per-day call counts in `.qa-harness/ai-usage.json` (shared by the panel and the CLI)."""

    def __init__(self, workspace_root: str):
        self.path = Path(workspace_root) / ".qa-harness" / "ai-usage.json"

    def _load(self) -> Dict[str, Dict[str, int]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            days = data.get("days", {})
            return days if isinstance(days, dict) else {}
        except (OSError, ValueError):
            return {}

    def add(self, purpose: str, calls: int = 1, approx_tokens: int = 0) -> None:
        try:
            days = self._load()
            today = days.setdefault(_today(), {})
            today[purpose] = int(today.get(purpose, 0)) + calls
            today[f"{purpose}_tokens"] = int(today.get(f"{purpose}_tokens", 0)) + approx_tokens
            cutoff = (datetime.now(timezone.utc) - timedelta(days=LEDGER_DAYS)).strftime("%Y-%m-%d")
            days = {d: v for d, v in days.items() if d >= cutoff}
            write_json_atomic(self.path, {"days": days})
        except OSError as exc:
            # Metering must never break a run.
            logger.warning("Could not update AI usage ledger: %s", exc)

    def today(self, purpose: Optional[str] = None) -> int:
        day = self._load().get(_today(), {})
        if purpose:
            return int(day.get(purpose, 0))
        return sum(int(day.get(p, 0)) for p in PURPOSES)

    def summary(self, days: int = 7) -> Dict[str, object]:
        data = self._load()
        recent = sorted(data.items(), reverse=True)[:days]
        return {"today": data.get(_today(), {}), "recent": [{"date": d, **v} for d, v in recent]}


class MeteredLLM(LLMProvider):
    """Counts every call of `inner` under `purpose` and forwards the purpose to the provider."""

    def __init__(
        self,
        inner: LLMProvider,
        purpose: str,
        counter: Optional[UsageCounter] = None,
        ledger: Optional[AIUsageLedger] = None,
    ):
        self.inner = inner
        self.purpose = purpose
        self.counter = counter or UsageCounter()
        self.ledger = ledger

    async def initialize(self) -> None:
        await self.inner.initialize()

    async def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        prompt_chars = _chars(messages)
        reply_chars = 0
        try:
            response = await self.inner.chat_with_purpose(
                self.purpose, messages, tools=tools, temperature=temperature
            )
            reply_chars = len(response.content or "")
            return response
        finally:
            # Failed calls are counted too: they may still have used provider quota.
            self.counter.record(self.purpose, prompt_chars, reply_chars)
            if self.ledger:
                self.ledger.add(self.purpose, 1, (prompt_chars + reply_chars) // 4)

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        response = await self.chat(messages, tools, temperature)
        yield response.content or ""
