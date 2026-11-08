"""Aggregated regression report across every executed suite (HTML zero-JS, Markdown, JSON)."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, Field

from qa_engine.security.paths import resolve_safe_path


class RegressionSuiteResult(BaseModel):
    slug: str
    module: str
    version: int
    status: str  # "passed", "failed", "error"
    total: int = 0
    passed: int = 0
    failed: int = 0
    flaky: int = 0
    blocked: int = 0
    skipped: int = 0
    duration_seconds: float = 0.0
    newly_failing: List[str] = Field(default_factory=list)
    fixed: List[str] = Field(default_factory=list)
    report_html: Optional[str] = None
    error: Optional[str] = None


class RegressionReport(BaseModel):
    regression_id: str
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    )
    triggered_by: str = ""
    tag: Optional[str] = None
    environment: Optional[str] = None
    suites: List[RegressionSuiteResult] = Field(default_factory=list)

    @property
    def totals(self) -> Dict[str, int]:
        keys = ("total", "passed", "failed", "flaky", "blocked", "skipped")
        return {k: sum(getattr(s, k) for s in self.suites) for k in keys}


def compare_statuses(previous: Dict[str, str], current: Dict[str, str]) -> Dict[str, List[str]]:
    newly_failing = sorted(
        tc for tc, st in current.items() if st == "failed" and previous.get(tc) == "passed"
    )
    fixed = sorted(
        tc for tc, st in current.items() if st == "passed" and previous.get(tc) == "failed"
    )
    return {"newly_failing": newly_failing, "fixed": fixed}


def write_regression_report(workspace_root: Path, report: RegressionReport) -> Dict[str, Path]:
    base = Path(workspace_root).resolve() / ".qa-harness" / "regressions"
    out_dir = resolve_safe_path(base, report.regression_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(str(Path(__file__).parent / "templates")), autoescape=True
    )
    context = {**report.model_dump(), "totals": report.totals}
    html = env.get_template("regression.html.jinja2").render(context)
    if "<script" in html.lower():
        raise ValueError("Security invariant violation: HTML report must not contain scripts.")
    md = env.get_template("regression.md.jinja2").render(context)

    paths = {
        "html": out_dir / "regression.html",
        "markdown": out_dir / "regression.md",
        "json": out_dir / "regression.json",
    }
    paths["html"].write_text(html, encoding="utf-8")
    paths["markdown"].write_text(md, encoding="utf-8")
    paths["json"].write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return paths
