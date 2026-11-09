"""Agent activity steps streamed to the UI (``activity`` notifications).

Each step is reported as ``start`` -> zero or more ``update`` -> ``end`` with a status of
``done``, ``failed``, or ``cancelled``. Kinds describe what the agent is doing so the panel can
show an icon and verb: read, think, browse, wait, write, check, save, run, investigate, report.
Steps are informational only; workflow results never depend on them.
"""

import asyncio
import itertools
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)
Notify = Callable[[str, Dict[str, Any]], Awaitable[None]]

KINDS = (
    "read",
    "think",
    "browse",
    "wait",
    "write",
    "check",
    "save",
    "run",
    "investigate",
    "report",
)


class Step:
    def __init__(self, reporter: "ActivityReporter", step_id: str, kind: str, title: str):
        self._reporter = reporter
        self.id = step_id
        self.kind = kind
        self.title = title
        self.result: Optional[str] = None
        self.status = "done"
        self.started = time.monotonic()

    async def update(self, detail: str) -> None:
        await self._reporter.emit({"id": self.id, "phase": "update", "detail": detail})

    def done(self, result: str, status: str = "done") -> None:
        """Set the summary (and optionally 'failed') shown when the step ends."""
        self.result = result
        self.status = status


class ActivityReporter:
    def __init__(self, notify: Notify):
        self._notify = notify
        self._ids = itertools.count(1)

    async def emit(self, params: Dict[str, Any]) -> None:
        try:
            await self._notify("activity", params)
        except Exception as exc:  # noqa: BLE001 - the UI feed must never break a workflow
            logger.debug("Dropped activity event %s: %s", params.get("id"), exc)

    @asynccontextmanager
    async def step(self, kind: str, title: str, detail: str = "") -> AsyncIterator[Step]:
        step = Step(self, f"step-{next(self._ids)}", kind if kind in KINDS else "think", title)
        await self.emit(
            {
                "id": step.id,
                "phase": "start",
                "kind": step.kind,
                "title": title,
                "detail": detail,
                "ts": time.time(),
            }
        )
        status, result = "done", None
        try:
            yield step
            status, result = step.status, step.result
        except asyncio.CancelledError:
            status, result = "cancelled", "Cancelled"
            raise
        except Exception as exc:
            status, result = "failed", str(exc).splitlines()[0][:240] if str(exc) else "Failed"
            raise
        finally:
            await self.emit(
                {
                    "id": step.id,
                    "phase": "end",
                    "status": status,
                    "detail": result,
                    "duration_ms": int((time.monotonic() - step.started) * 1000),
                }
            )
