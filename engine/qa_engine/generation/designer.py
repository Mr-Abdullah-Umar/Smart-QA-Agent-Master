"""Requirement-driven AI test design: analysis, page selection, case design, and revision.

All model output is schema-validated (with repair) and semantically checked before use:
navigation must stay inside the confirmed domain allowlist and every case must trace to an
acceptance criterion. Requirement text and page content are passed as untrusted data.
"""

import json
import re
from typing import Dict, List, Optional, Sequence, Set
from urllib.parse import urljoin

from pydantic import BaseModel, Field

from qa_engine.browser.snapshot import SnapshotResult
from qa_engine.generation.actions import TestAction, secret_names
from qa_engine.generation.auto_design import module_code
from qa_engine.generation.testcases import (
    TEST_TYPES,
    CoverageMatrix,
    CoverageMatrixItem,
    TestCase,
    TestCaseCategory,
    TestCaseCollection,
    TestCasePriority,
)
from qa_engine.llm.prompts.analysis import ANALYSIS_SYSTEM_PROMPT
from qa_engine.llm.prompts.test_design import TEST_DESIGN_SYSTEM_PROMPT
from qa_engine.llm.provider import LLMProvider
from qa_engine.llm.schemas import RequirementAnalysis
from qa_engine.llm.structured import chat_structured, schema_instructions
from qa_engine.security.ssrf import validate_destination_url

MAX_SNAPSHOT_CHARS = 9000
MAX_TOTAL_SNAPSHOT_CHARS = 30000
_AC_LINE = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)]|AC[-\s]?\d+[:.)-]?)\s*", re.IGNORECASE)


def parse_acceptance_criteria(text: str) -> List[Dict[str, str]]:
    """One criterion per non-empty line, numbered AC-1..AC-n (bullets/numbering stripped)."""
    items = []
    for line in (text or "").splitlines():
        clean = _AC_LINE.sub("", line).strip()
        if clean:
            items.append({"id": f"AC-{len(items) + 1}", "text": clean})
    return items


class PageSelection(BaseModel):
    urls: List[str] = Field(default_factory=list, description="Absolute URLs to explore")
    reason: str = ""


class DesignedCase(BaseModel):
    tc_id: Optional[str] = Field(default=None, description="Keep existing ID when revising")
    title: str
    ac_ref: str = Field(description="Acceptance criterion ID, e.g. AC-1")
    category: TestCaseCategory = TestCaseCategory.FUNCTIONAL_POSITIVE
    priority: TestCasePriority = TestCasePriority.P2
    priority_rationale: Optional[str] = None
    test_types: List[str] = Field(default_factory=list)
    preconditions: List[str] = Field(default_factory=list)
    test_data: Dict[str, str] = Field(default_factory=dict)
    steps: List[str] = Field(min_length=1)
    expected_result: str
    actions: List[TestAction] = Field(min_length=1)


class TestDesignResult(BaseModel):
    __test__ = False
    testcases: List[DesignedCase] = Field(min_length=1)
    notes: Optional[str] = None


DESIGN_RULES = f"""
OUTPUT RULES FOR THIS HARNESS:
- Each case needs an executable `actions` plan. The FIRST action must be `goto` with value ""
  (the start URL), a path relative to it (e.g. "/login"), or an absolute in-scope URL.
- Locate elements ONLY with user-facing locators taken from the page snapshots provided:
  {{"by":"role","role":"button","value":"Sign in"}}, or by "label", "placeholder", "text",
  "test_id". Copy accessible names exactly as they appear in the snapshot.
- Every case must end with at least one `expect_*` assertion that proves `expected_result`.
- Credentials and sensitive inputs MUST use placeholders like "{{{{secret.LOGIN_PASSWORD}}}}"
  (UPPER_SNAKE names). Use "{{{{unique}}}}" for values that must be unique per run.
  Never put real secrets in any field.
- Avoid irreversible actions (deleting data, payments, sending messages to real people)
  unless an acceptance criterion explicitly requires them.
- `ac_ref` must be one of the given acceptance criterion IDs. Cover EVERY criterion with at
  least one positive case, plus negative/boundary cases where the criterion implies them.
- `test_types` is a subset of {list(TEST_TYPES)}. Mark the most critical happy path cases
  "smoke" and "sanity"; mark all cases "regression".
- P1 cases need a one-line `priority_rationale`.
- Prefer 4-15 focused cases. Steps are plain user language (no selectors or code).
"""


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n... [truncated]"


def _snapshots_block(snapshots: Sequence[SnapshotResult]) -> str:
    parts, used = [], 0
    for snap in snapshots:
        budget = min(MAX_SNAPSHOT_CHARS, MAX_TOTAL_SNAPSHOT_CHARS - used)
        if budget <= 500:
            break
        body = _truncate(snap.text_representation, budget)
        used += len(body)
        parts.append(f"### PAGE {snap.url}\nTitle: {snap.title}\n{body}")
    return "\n\n".join(parts) or "No pages explored."


def _criteria_block(criteria: List[Dict[str, str]]) -> str:
    return "\n".join(f"{c['id']}: {c['text']}" for c in criteria) or "None provided."


class AITestDesigner:
    """Drives the LLM through analysis, exploration planning, design, and revision."""

    def __init__(
        self,
        llm: LLMProvider,
        module: str,
        start_url: str,
        allowed_domains: List[str],
    ):
        self.llm = llm
        self.module = module
        self.start_url = start_url
        self.allowed_domains = allowed_domains

    async def analyze(
        self, requirement: str, criteria: List[Dict[str, str]]
    ) -> RequirementAnalysis:
        prompt = (
            f"Module under test: {self.module}\nStart URL: {self.start_url}\n\n"
            "--- BEGIN UNTRUSTED REQUIREMENT DATA ---\n"
            f"{requirement}\n\nAcceptance criteria:\n{_criteria_block(criteria)}\n"
            "--- END UNTRUSTED REQUIREMENT DATA ---\n\n"
            "Ask at most 5 clarification questions, and ONLY for information that blocks test "
            "design (e.g. which test account role to use, exact error message text, limits). "
            "If the criteria are testable as written, return an empty question list. Number "
            "questions Q-1, Q-2, ...\n\n" + schema_instructions(RequirementAnalysis)
        )
        return await chat_structured(
            self.llm,
            [
                {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            RequirementAnalysis,
        )

    def _in_scope(self, url: str) -> bool:
        ok, _ = validate_destination_url(url, self.allowed_domains, resolve_dns=False)
        return ok

    async def choose_pages(
        self,
        requirement: str,
        criteria: List[Dict[str, str]],
        start_snapshot: SnapshotResult,
        links: List[Dict[str, str]],
        max_pages: int = 4,
    ) -> List[str]:
        """Let the model pick additional in-scope pages relevant to the requirement."""
        candidates = [link for link in links if self._in_scope(link["href"])]
        if not candidates:
            return []
        link_lines = "\n".join(f"- {c['href']}  ({c['text'] or 'no text'})" for c in candidates)
        prompt = (
            f"Requirement for module '{self.module}':\n{_truncate(requirement, 3000)}\n\n"
            f"Acceptance criteria:\n{_criteria_block(criteria)}\n\n"
            f"Start page: {start_snapshot.url} (title: {start_snapshot.title})\n"
            "--- BEGIN UNTRUSTED LINK LIST ---\n"
            f"{link_lines}\n--- END UNTRUSTED LINK LIST ---\n\n"
            f"Choose at most {max_pages} URLs from the list whose pages are needed to design "
            "tests for these criteria. Choose none if the start page is enough.\n\n"
            + schema_instructions(PageSelection)
        )
        allowed = {c["href"] for c in candidates}
        selection = await chat_structured(
            self.llm,
            [{"role": "user", "content": prompt}],
            PageSelection,
            extra_check=lambda s: [f"URL not in list: {u}" for u in s.urls if u not in allowed],
        )
        return selection.urls[:max_pages]

    def _check_design(self, result: TestDesignResult, criteria: List[Dict[str, str]]) -> List[str]:
        problems = []
        valid_acs = {c["id"] for c in criteria}
        for idx, case in enumerate(result.testcases, start=1):
            label = case.tc_id or f"case #{idx}"
            if valid_acs and case.ac_ref not in valid_acs:
                problems.append(
                    f"{label}: ac_ref '{case.ac_ref}' is not one of {sorted(valid_acs)}"
                )
            if case.actions[0].action != "goto":
                problems.append(f"{label}: first action must be 'goto'.")
            if not any(a.action.startswith("expect_") for a in case.actions):
                problems.append(f"{label}: needs at least one expect_* assertion.")
            for action in case.actions:
                if action.action == "goto":
                    url = urljoin(self.start_url, action.value or "")
                    if not self._in_scope(url):
                        problems.append(f"{label}: goto '{action.value}' leaves the allowed scope.")
        covered = {c.ac_ref for c in result.testcases}
        missing = sorted(valid_acs - covered)
        if missing:
            problems.append(f"No test case covers: {', '.join(missing)}")
        return problems

    async def design(
        self,
        requirement: str,
        criteria: List[Dict[str, str]],
        clarifications: List[Dict[str, str]],
        snapshots: Sequence[SnapshotResult],
    ) -> TestDesignResult:
        answers = "\n".join(f"- Q: {c['question']}\n  A: {c['answer']}" for c in clarifications)
        prompt = (
            f"Design test cases for module '{self.module}'. Start URL: {self.start_url}\n"
            f"Allowed domains: {', '.join(self.allowed_domains)}\n\n"
            "--- BEGIN UNTRUSTED REQUIREMENT DATA ---\n"
            f"{requirement}\n\nAcceptance criteria:\n{_criteria_block(criteria)}\n"
            f"\nClarifications from the QA engineer:\n{answers or 'None.'}\n"
            "--- END UNTRUSTED REQUIREMENT DATA ---\n\n"
            "--- BEGIN UNTRUSTED PAGE SNAPSHOTS (ARIA trees) ---\n"
            f"{_snapshots_block(snapshots)}\n--- END UNTRUSTED PAGE SNAPSHOTS ---\n"
            f"{DESIGN_RULES}\n" + schema_instructions(TestDesignResult)
        )
        return await chat_structured(
            self.llm,
            [
                {"role": "system", "content": TEST_DESIGN_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            TestDesignResult,
            extra_check=lambda r: self._check_design(r, criteria),
        )

    async def revise(
        self,
        current: TestCaseCollection,
        comments: str,
        requirement: str,
        criteria: List[Dict[str, str]],
        snapshots: Sequence[SnapshotResult],
    ) -> TestDesignResult:
        current_json = json.dumps(
            [tc.model_dump(mode="json", exclude={"version", "status"}) for tc in current.testcases],
            ensure_ascii=False,
        )
        prompt = (
            f"Revise the test cases of module '{self.module}' according to the reviewer.\n"
            "Return the COMPLETE revised list. Keep `tc_id` for cases you keep or modify; use "
            "null `tc_id` for new cases; omit cases the reviewer wants removed.\n\n"
            "--- BEGIN UNTRUSTED REQUIREMENT DATA ---\n"
            f"{requirement}\n\nAcceptance criteria:\n{_criteria_block(criteria)}\n"
            "--- END UNTRUSTED REQUIREMENT DATA ---\n\n"
            f"Current test cases (JSON):\n{current_json}\n\n"
            f"--- BEGIN REVIEWER COMMENTS ---\n{comments}\n--- END REVIEWER COMMENTS ---\n\n"
            "--- BEGIN UNTRUSTED PAGE SNAPSHOTS (ARIA trees) ---\n"
            f"{_snapshots_block(snapshots)}\n--- END UNTRUSTED PAGE SNAPSHOTS ---\n"
            f"{DESIGN_RULES}\n" + schema_instructions(TestDesignResult)
        )
        return await chat_structured(
            self.llm,
            [
                {"role": "system", "content": TEST_DESIGN_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            TestDesignResult,
            extra_check=lambda r: self._check_design(r, criteria),
        )


def build_collection(
    result: TestDesignResult,
    module: str,
    requirement_ref: str,
    version: int = 1,
    existing_ids: Optional[Set[str]] = None,
) -> TestCaseCollection:
    """Convert model output into approved-schema test cases with stable TC-<MODULE>-NNN IDs."""
    code = module_code(module)
    keep = existing_ids or set()
    used: Set[str] = set()
    numbers = [
        int(m.group(1))
        for tc_id in keep
        if (m := re.fullmatch(rf"TC-{re.escape(code)}-(\d+)", tc_id))
    ]
    counter = max(numbers, default=0)

    cases: List[TestCase] = []
    for designed in result.testcases:
        tc_id = designed.tc_id if designed.tc_id in keep and designed.tc_id not in used else None
        if tc_id is None:
            counter += 1
            tc_id = f"TC-{code}-{counter:03d}"
        used.add(tc_id)
        types = designed.test_types or ["regression"]
        if "regression" not in types:
            types = list(types) + ["regression"]
        cases.append(
            TestCase(
                tc_id=tc_id,
                title=designed.title,
                requirement_ref=requirement_ref,
                ac_ref=designed.ac_ref,
                category=designed.category,
                priority=designed.priority,
                priority_rationale=designed.priority_rationale
                or ("Critical path" if designed.priority == TestCasePriority.P1 else None),
                preconditions=designed.preconditions,
                test_data=designed.test_data,
                steps=designed.steps,
                expected_result=designed.expected_result,
                test_types=types,
                actions=designed.actions,
                version=version,
            )
        )
    return TestCaseCollection(version=version, testcases=cases)


def build_coverage(
    collection: TestCaseCollection, criteria: List[Dict[str, str]]
) -> CoverageMatrix:
    items = []
    for crit in criteria:
        covered = [tc.tc_id for tc in collection.testcases if tc.ac_ref == crit["id"]]
        items.append(
            CoverageMatrixItem(
                requirement_id=crit["id"],
                requirement_text=crit["text"],
                covered_test_case_ids=covered,
                has_gaps=not covered,
            )
        )
    covered_count = sum(1 for i in items if not i.has_gaps)
    return CoverageMatrix(
        items=items,
        total_requirements=len(items),
        covered_requirements=covered_count,
        coverage_percentage=round(covered_count / len(items) * 100, 1) if items else 0.0,
    )


def required_secrets(collection: TestCaseCollection) -> List[str]:
    names: Set[str] = set()
    for tc in collection.testcases:
        names.update(secret_names(tc.actions))
    return sorted(names)


def unverified_locators(
    collection: TestCaseCollection, snapshots: Sequence[SnapshotResult]
) -> List[str]:
    """Role+name locators that do not appear in any explored snapshot (e.g. post-login UI)."""
    known = {
        (el.role.lower(), el.name.strip().lower())
        for snap in snapshots
        for el in snap.elements.values()
    }
    text = "\n".join(s.text_representation.lower() for s in snapshots)
    warnings = []
    for tc in collection.testcases:
        for action in tc.actions:
            t = action.target
            if not t or not t.value:
                continue
            if t.by == "role":
                if (t.role, t.value.strip().lower()) in known or f'"{t.value.lower()}' in text:
                    continue
            elif t.value.lower() in text:
                continue
            warnings.append(f"{tc.tc_id}: {t.role or t.by} '{t.value}'")
    return sorted(set(warnings))
