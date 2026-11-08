"""AI Failure Investigation and Root Cause Analysis Classifier.

Implements Section 8.11 & Appendix B specifications:
- Segregates observed facts from speculative hypotheses.
- Programmatically verifies that all cited evidence IDs exist on disk.
- Classifies failures into 7 mutually exclusive categories.
- Enforces Gate 2 human sign-off requirement for any 'Product defect'.
"""

import json
import logging
from typing import Dict, Optional

from qa_engine.execution.runner import TestCaseOutcome
from qa_engine.investigation.evidence import EvidenceIndex
from qa_engine.investigation.schemas import (
    FailureCategory,
    InvestigationFact,
    InvestigationHypothesis,
    InvestigationReport,
)
from qa_engine.llm.provider import LLMProvider
from qa_engine.llm.structured import extract_json_object

logger = logging.getLogger(__name__)


INVESTIGATION_SYSTEM_PROMPT = """You are a Principal QA and Root Cause Analysis Engineer.
Analyze the test failure and evidence to determine the root cause per Appendix B.

Rules:
1. Categorize the failure into EXACTLY ONE of the following 7 categories:
   - Product defect
   - Automation issue
   - Test data issue
   - Environment issue
   - Unclear requirement
   - Flaky
   - Insufficient evidence
2. Segregate OBSERVED FACTS from HYPOTHESES:
   - Every single fact MUST cite a verified Evidence ID (e.g. EV-001).
   - NEVER invent or cite an Evidence ID that is not in the provided evidence list.
3. Provide confidence between 0.0 and 1.0.
4. Return pure JSON matching the InvestigationReport schema without markdown fences.
"""


class FailureClassifier:
    """Investigates test failures using evidence-based reasoning and rule/LLM classification."""

    def __init__(self, evidence_index: EvidenceIndex, llm: Optional[LLMProvider] = None):
        self.evidence_index = evidence_index
        self.llm = llm
        self.reports: Dict[str, InvestigationReport] = {}

    def _next_failure_id(self) -> str:
        return f"FAIL-{len(self.reports) + 1:03d}"

    def investigate(
        self,
        outcome: TestCaseOutcome,
        requirement_ref: Optional[str] = None,
    ) -> InvestigationReport:
        """Rule-based root cause analysis (no LLM) for a failed or flaky outcome."""
        failure_id = self._next_failure_id()
        return self._rule_based(failure_id, outcome) or self._build_heuristic_fallback(
            failure_id, outcome
        )

    async def investigate_async(
        self,
        outcome: TestCaseOutcome,
        requirement_ref: Optional[str] = None,
    ) -> InvestigationReport:
        """Root cause analysis using deterministic rules first, then the LLM if connected."""
        failure_id = self._next_failure_id()
        report = self._rule_based(failure_id, outcome)
        if report:
            return report
        if self.llm:
            try:
                report = await self._run_llm_investigation(failure_id, outcome, requirement_ref)
                if report:
                    self._verify_and_sanitize_report(report)
                    self.reports[failure_id] = report
                    return report
            except Exception as exc:
                logger.warning(
                    "LLM investigation failed for %s, using fallback: %s", outcome.tc_id, exc
                )
        return self._build_heuristic_fallback(failure_id, outcome)

    def _rule_based(
        self, failure_id: str, outcome: TestCaseOutcome
    ) -> Optional[InvestigationReport]:
        if outcome.status == "flaky":
            return self._build_flaky_report(failure_id, outcome)

        err_text = (outcome.error_message or "") + "\n" + (outcome.stack_trace or "")

        # Environment failure detection (HTTP 5xx, network timeout, connection refused)
        if any(
            x in err_text
            for x in (
                "500 Internal Server Error",
                "502 Bad Gateway",
                "503 Service Unavailable",
                "504 Gateway Timeout",
                "ECONNREFUSED",
                "net::ERR_CONNECTION_REFUSED",
            )
        ):
            return self._build_deterministic_report(
                failure_id=failure_id,
                outcome=outcome,
                category=FailureCategory.ENVIRONMENT_FAILURE,
                reason="Backend server or network infrastructure returned 5xx / connection error.",
            )
        return None

    def _build_flaky_report(self, failure_id: str, outcome: TestCaseOutcome) -> InvestigationReport:
        """Build report for retried passing test marked flaky."""
        facts = []
        citations = []
        for ev_id, item in self.evidence_index.items.items():
            if outcome.tc_id.lower() in item.description.lower() or "log" in item.category:
                facts.append(
                    InvestigationFact(
                        statement="Test failed during initial pass but succeeded upon retry.",
                        evidence_id=ev_id,
                    )
                )
                citations.append(ev_id)
                break

        if not facts and self.evidence_index.items:
            first_id = next(iter(self.evidence_index.items))
            facts.append(
                InvestigationFact(
                    statement="Test outcome marked flaky after passing second retry pass.",
                    evidence_id=first_id,
                )
            )
            citations.append(first_id)

        report = InvestigationReport(
            failure_id=failure_id,
            tc_id=outcome.tc_id,
            category=FailureCategory.FLAKY,
            confidence=0.95,
            facts=facts,
            hypotheses=[
                InvestigationHypothesis(
                    hypothesis="Intermittent race condition or asynchronous DOM render delay.",
                    supporting_indicators=[
                        "Initial execution timed out or failed an assertion.",
                        "Retry pass succeeded without code modifications.",
                    ],
                )
            ],
            evidence_citations=citations,
            reproduction_steps=[
                "Run test under high network/CPU latency",
                "Observe intermittent failure",
            ],
            recommended_action="Replace loose timeouts with web-first Playwright expect locators.",
            preventive_measure="Enforce strict locator waiting and eliminate race conditions.",
            requires_human_signoff=False,
        )
        self.reports[failure_id] = report
        return report

    def _build_deterministic_report(
        self,
        failure_id: str,
        outcome: TestCaseOutcome,
        category: FailureCategory,
        reason: str,
    ) -> InvestigationReport:
        facts = []
        citations = []
        for ev_id in self.evidence_index.items:
            facts.append(
                InvestigationFact(
                    statement=reason,
                    evidence_id=ev_id,
                )
            )
            citations.append(ev_id)
            break

        report = InvestigationReport(
            failure_id=failure_id,
            tc_id=outcome.tc_id,
            category=category,
            confidence=0.90,
            facts=facts,
            hypotheses=[
                InvestigationHypothesis(
                    hypothesis="Application under test or upstream dependency is unreachable.",
                    supporting_indicators=[reason],
                )
            ],
            evidence_citations=citations,
            reproduction_steps=[f"Execute {outcome.tc_id} against target server"],
            recommended_action="Check application logs and verify backend container health.",
            preventive_measure="Add automated smoke tests before running full QA harness.",
            requires_human_signoff=False,
        )
        self.reports[failure_id] = report
        return report

    def _build_heuristic_fallback(
        self, failure_id: str, outcome: TestCaseOutcome
    ) -> InvestigationReport:
        """Heuristic fallback when LLM is unavailable."""
        err_msg = outcome.error_message or ""
        stack = outcome.stack_trace or ""

        # Default to Automation issue if Timeout waiting for locator or SyntaxError
        if "TimeoutError" in stack or "waiting for locator" in err_msg:
            category = FailureCategory.AUTOMATION_ISSUE
            rec = "Verify selector against updated DOM snapshot and update Page Object."
        elif "AssertionError" in stack:
            category = FailureCategory.PRODUCT_DEFECT
            rec = "Investigate application state regression and confirm with dev team."
        else:
            category = FailureCategory.INSUFFICIENT_EVIDENCE
            rec = "Collect detailed Playwright trace and server logs for reproduction."

        facts = []
        citations = []
        if self.evidence_index.items:
            first_id = next(iter(self.evidence_index.items))
            facts.append(
                InvestigationFact(
                    statement=f"Test failed with message: {err_msg[:200]}",
                    evidence_id=first_id,
                )
            )
            citations.append(first_id)

        report = InvestigationReport(
            failure_id=failure_id,
            tc_id=outcome.tc_id,
            category=category,
            confidence=0.75,
            facts=facts,
            hypotheses=[
                InvestigationHypothesis(
                    hypothesis="Observed failure condition matches error pattern.",
                    supporting_indicators=[err_msg[:150]],
                )
            ],
            evidence_citations=citations,
            reproduction_steps=[f"Run pytest for {outcome.tc_id}"],
            recommended_action=rec,
            preventive_measure="Keep Page Object locators synchronized with ARIA roles.",
            requires_human_signoff=(category == FailureCategory.PRODUCT_DEFECT),
        )
        self.reports[failure_id] = report
        return report

    async def _run_llm_investigation(
        self,
        failure_id: str,
        outcome: TestCaseOutcome,
        requirement_ref: Optional[str],
    ) -> Optional[InvestigationReport]:
        """Query LLM for structured RCA."""
        if not self.llm:
            return None

        # Format list of verified evidence items
        ev_lines = [
            f"- [{item.evidence_id}]: ({item.category}) {item.description}"
            for item in self.evidence_index.items.values()
        ]
        evidence_prompt = "\n".join(ev_lines) if ev_lines else "None recorded."

        user_prompt = f"""Investigate test failure for {outcome.tc_id}.
Requirement Ref: {requirement_ref or "N/A"}
Error Message: {outcome.error_message or "N/A"}
Stack Trace:
{outcome.stack_trace or "N/A"}

Available Evidence IDs:
{evidence_prompt}

Analyze the root cause and return JSON matching the schema."""

        messages = [
            {"role": "system", "content": INVESTIGATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        response = await self.llm.chat(messages, temperature=0.1)
        data = json.loads(extract_json_object(response.content or ""))
        data["failure_id"] = failure_id
        data["tc_id"] = outcome.tc_id
        return InvestigationReport.model_validate(data)

    def _verify_and_sanitize_report(self, report: InvestigationReport) -> None:
        """Enforce strict evidence citation verification and Gate 2 rules."""
        verified_facts = []
        valid_citations = set()

        for fact in report.facts:
            clean_id = fact.evidence_id.strip("[]")
            if self.evidence_index.verify_citation(clean_id):
                fact.evidence_id = clean_id
                verified_facts.append(fact)
                valid_citations.add(clean_id)
            else:
                logger.warning(
                    "Stripping hallucinated evidence citation '%s' from fact in %s",
                    fact.evidence_id,
                    report.failure_id,
                )

        report.facts = verified_facts
        report.evidence_citations = sorted(valid_citations)

        # Enforce Gate 2 rule: Product defect requires human sign-off
        if report.category == FailureCategory.PRODUCT_DEFECT:
            report.requires_human_signoff = True
        else:
            report.requires_human_signoff = False

    def sign_off_defect(
        self,
        failure_id: str,
        approver: str,
        notes: Optional[str] = None,
    ) -> bool:
        """Gate 2 human sign-off for confirmed Product Defect."""
        if failure_id not in self.reports:
            return False

        report = self.reports[failure_id]
        if report.category != FailureCategory.PRODUCT_DEFECT:
            return False

        report.gate_2_signed_off = True
        report.signed_off_by = approver
        report.signoff_notes = notes
        return True
