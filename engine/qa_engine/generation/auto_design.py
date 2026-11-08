"""Deterministic smoke test design from an explored page's ARIA snapshot.

Used when no AI provider is connected (or for quick smoke suites). Every drafted case is
non-destructive: it only reads the page or types into text inputs, never submits forms or
clicks controls. Each case carries an executable action plan.
"""

import re
import unicodedata
from typing import List, Set

from qa_engine.browser.snapshot import SnapshotResult
from qa_engine.generation.actions import ElementLocator, TestAction
from qa_engine.generation.testcases import (
    TestCase,
    TestCaseCategory,
    TestCaseCollection,
    TestCasePriority,
)

_HEADING_PATTERN = re.compile(r'^\s*-\s+heading\s+"([^"\\]+)"', re.MULTILINE)

_VISIBLE_ROLES = ("button", "link", "checkbox", "radio", "combobox", "tab", "switch")
_FILLABLE_ROLES = ("textbox", "searchbox")
SAMPLE_TEXT = "qa-harness-sample"


def module_code(module_name: str) -> str:
    """Upper-case ID fragment for a module, e.g. 'User Login' -> 'USER-LOGIN'."""
    code = re.sub(r"[^A-Za-z0-9]+", "-", module_name).strip("-").upper()
    return code[:24] or "MODULE"


def _usable_name(name: str) -> bool:
    return bool(name) and len(name) <= 80 and '"' not in name and "\\" not in name


def _display_name(name: str) -> str:
    """Strip icon-font glyphs (private-use code points) and control chars for human text."""
    visible = "".join(ch for ch in name if ch.isprintable() and unicodedata.category(ch) != "Co")
    return " ".join(visible.split()) or name


def design_smoke_testcases(
    snapshot: SnapshotResult,
    max_element_cases: int = 6,
    requirement_ref: str = "REQ-SMOKE",
    module: str = "SMOKE",
) -> TestCaseCollection:
    """Draft Appendix A smoke cases covering page load, headings, and key controls."""
    cases: List[TestCase] = []
    code = module_code(module)

    def next_id() -> str:
        return f"TC-{code}-{len(cases) + 1:03d}"

    open_page = TestAction(action="goto", value="", description="Open the start URL")
    title = snapshot.title.strip()
    if title:
        cases.append(
            TestCase(
                tc_id=next_id(),
                title=f"Verify the page loads with title '{title}'",
                requirement_ref=requirement_ref,
                category=TestCaseCategory.FUNCTIONAL_POSITIVE,
                priority=TestCasePriority.P1,
                priority_rationale="Page availability blocks every other check",
                preconditions=["Target URL is reachable"],
                steps=["Navigate to the start URL", "Observe the browser tab title"],
                expected_result=f"The page title contains '{title}'",
                test_types=["smoke", "sanity"],
                actions=[open_page, TestAction(action="expect_title", value=title)],
            )
        )

    heading_match = _HEADING_PATTERN.search(snapshot.text_representation)
    if heading_match and _usable_name(heading_match.group(1).strip()):
        heading = heading_match.group(1).strip()
        cases.append(
            TestCase(
                tc_id=next_id(),
                title=f"Verify the main heading '{heading}' is displayed",
                requirement_ref=requirement_ref,
                category=TestCaseCategory.UI,
                priority=TestCasePriority.P2,
                preconditions=["Target URL is reachable"],
                steps=["Navigate to the start URL", "Locate the main page heading"],
                expected_result=f"The heading '{heading}' is visible",
                test_types=["smoke"],
                actions=[
                    open_page,
                    TestAction(
                        action="expect_visible",
                        target=ElementLocator(by="role", role="heading", value=heading),
                    ),
                ],
            )
        )

    seen: Set[str] = set()
    element_cases = 0
    ordered = sorted(
        snapshot.elements.values(),
        key=lambda el: (
            0 if el.role in _FILLABLE_ROLES else 1 if el.role == "button" else 2,
            int(el.ref_id.lstrip("#") or 0),
        ),
    )
    for el in ordered:
        if element_cases >= max_element_cases:
            break
        sig = f"{el.role}:{el.name}"
        if el.nth > 0 or el.disabled or sig in seen or not _usable_name(el.name):
            continue
        if el.role not in _FILLABLE_ROLES and el.role not in _VISIBLE_ROLES:
            continue
        seen.add(sig)
        element_cases += 1
        label = _display_name(el.name)
        target = ElementLocator(by="role", role=el.role, value=el.name, exact=True)

        if el.role in _FILLABLE_ROLES:
            cases.append(
                TestCase(
                    tc_id=next_id(),
                    title=f"Verify the '{label}' field accepts text input",
                    requirement_ref=requirement_ref,
                    category=TestCaseCategory.FUNCTIONAL_POSITIVE,
                    priority=TestCasePriority.P2,
                    preconditions=["Target URL is reachable"],
                    test_data={"value": SAMPLE_TEXT},
                    steps=[
                        "Navigate to the start URL",
                        f"Type '{SAMPLE_TEXT}' into the '{label}' field",
                    ],
                    expected_result=f"The '{label}' field shows the typed value",
                    test_types=["smoke"],
                    actions=[
                        open_page,
                        TestAction(action="fill", target=target, value=SAMPLE_TEXT),
                        TestAction(action="expect_value", target=target, value=SAMPLE_TEXT),
                    ],
                )
            )
        else:
            cases.append(
                TestCase(
                    tc_id=next_id(),
                    title=f"Verify the '{label}' {el.role} is displayed",
                    requirement_ref=requirement_ref,
                    category=TestCaseCategory.UI,
                    priority=TestCasePriority.P2 if el.role == "button" else TestCasePriority.P3,
                    preconditions=["Target URL is reachable"],
                    steps=["Navigate to the start URL", f"Locate the '{label}' {el.role}"],
                    expected_result=f"The '{label}' {el.role} is visible on the page",
                    test_types=["smoke"],
                    actions=[open_page, TestAction(action="expect_visible", target=target)],
                )
            )

    if not cases:
        cases.append(
            TestCase(
                tc_id=next_id(),
                title="Verify the page renders content",
                requirement_ref=requirement_ref,
                category=TestCaseCategory.FUNCTIONAL_POSITIVE,
                priority=TestCasePriority.P1,
                priority_rationale="Page availability blocks every other check",
                steps=["Navigate to the start URL"],
                expected_result="The page body is visible",
                test_types=["smoke", "sanity"],
            )
        )

    return TestCaseCollection(version=1, testcases=cases)
