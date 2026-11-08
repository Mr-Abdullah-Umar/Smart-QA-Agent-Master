"""Standardized Test Case Schema, Markdown serialization, and SHA-256 integrity hashing.

Enforces Section 8.5 & Appendix A specifications:
- Stored as validated JSON for machines, rendered as Markdown for people.
- Steps written from the user perspective (no code or selectors).
- Cryptographic SHA-256 hash binding for Gate 1 approval (T10 controls).
"""

import hashlib
import json
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class TestCaseCategory(str, Enum):
    __test__ = False
    FUNCTIONAL_POSITIVE = "Functional positive"
    FUNCTIONAL_NEGATIVE = "Functional negative"
    BOUNDARY = "Boundary"
    UI = "UI"
    ACCESSIBILITY = "Accessibility"
    RESPONSIVE = "Responsive"
    CROSS_BROWSER = "Cross-browser"
    CONSOLE_NETWORK = "Console and network"
    BASIC_PERFORMANCE = "Basic performance"
    PASSIVE_SECURITY = "Passive security"


class TestCasePriority(str, Enum):
    __test__ = False
    P1 = "P1"  # Critical path / core blocker
    P2 = "P2"  # Major functionality
    P3 = "P3"  # Minor / edge case
    P4 = "P4"  # Trivial / cosmetic


class TestCase(BaseModel):
    __test__ = False
    tc_id: str = Field(description="Unique identifier, e.g. TC-LOGIN-001")
    title: str = Field(description="One short sentence stating what is verified")
    requirement_ref: str = Field(description="Requirement ID or acceptance criterion traced to")
    category: TestCaseCategory = TestCaseCategory.FUNCTIONAL_POSITIVE
    priority: TestCasePriority = TestCasePriority.P2
    priority_rationale: Optional[str] = Field(
        default=None, description="Mandatory rationale for P1"
    )
    preconditions: List[str] = Field(
        default_factory=list, description="State required before execution"
    )
    test_data: Dict[str, str] = Field(
        default_factory=dict, description="Test data placeholders (e.g. {{TEST_USER}})"
    )
    steps: List[str] = Field(description="Numbered user-perspective actions (no selectors or code)")
    expected_result: str = Field(description="Observable, user-visible outcome")
    postconditions: Optional[str] = Field(default=None, description="State to restore after test")
    automation_candidate: bool = True
    automation_rationale: Optional[str] = None
    version: int = 1
    status: str = "draft"  # "draft", "approved", "rejected"


class CoverageMatrixItem(BaseModel):
    requirement_id: str
    requirement_text: str
    covered_test_case_ids: List[str] = Field(default_factory=list)
    has_gaps: bool = False
    notes: Optional[str] = None


class CoverageMatrix(BaseModel):
    items: List[CoverageMatrixItem] = Field(default_factory=list)
    total_requirements: int = 0
    covered_requirements: int = 0
    coverage_percentage: float = 0.0


class TestCaseCollection(BaseModel):
    __test__ = False
    version: int = 1
    testcases: List[TestCase] = Field(default_factory=list)

    def compute_sha256_hash(self) -> str:
        """Compute canonical SHA-256 hash over normalized test case content for Gate 1 approval."""
        canonical_list = []
        for tc in sorted(self.testcases, key=lambda x: x.tc_id):
            canonical_list.append(
                {
                    "tc_id": tc.tc_id,
                    "title": tc.title,
                    "requirement_ref": tc.requirement_ref,
                    "category": tc.category.value,
                    "priority": tc.priority.value,
                    "preconditions": tc.preconditions,
                    "test_data": tc.test_data,
                    "steps": tc.steps,
                    "expected_result": tc.expected_result,
                    "postconditions": tc.postconditions,
                    "automation_candidate": tc.automation_candidate,
                }
            )
        canonical_str = json.dumps(canonical_list, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    def compute_canonical_hash(self) -> str:
        """Alias for compute_sha256_hash()."""
        return self.compute_sha256_hash()

    def to_markdown(self) -> str:
        """Render test cases in Appendix A human-readable Markdown format."""
        md_lines = [
            f"# Test Cases Specification (Version {self.version})",
            "",
            f"**Total Cases:** {len(self.testcases)}  ",
            f"**Integrity Hash (SHA-256):** `{self.compute_sha256_hash()}`  ",
            "",
            "---",
            "",
        ]

        for tc in self.testcases:
            md_lines.append(f"## {tc.tc_id}: {tc.title}")
            md_lines.append("")
            md_lines.append(f"- **Requirement Reference:** {tc.requirement_ref}")
            md_lines.append(f"- **Category:** {tc.category.value}")
            md_lines.append(
                f"- **Priority:** {tc.priority.value}"
                + (f" ({tc.priority_rationale})" if tc.priority_rationale else "")
            )
            md_lines.append(
                f"- **Automation Candidate:** {'Yes' if tc.automation_candidate else 'No'}"
            )
            md_lines.append("")

            if tc.preconditions:
                md_lines.append("### Preconditions")
                for pre in tc.preconditions:
                    md_lines.append(f"- {pre}")
                md_lines.append("")

            if tc.test_data:
                md_lines.append("### Test Data")
                for k, v in tc.test_data.items():
                    md_lines.append(f"- **{k}:** `{v}`")
                md_lines.append("")

            md_lines.append("### Steps")
            for idx, step in enumerate(tc.steps, start=1):
                md_lines.append(f"{idx}. {step}")
            md_lines.append("")

            md_lines.append("### Expected Result")
            md_lines.append(tc.expected_result)
            md_lines.append("")

            if tc.postconditions:
                md_lines.append("### Postconditions")
                md_lines.append(tc.postconditions)
                md_lines.append("")

            md_lines.append("---")
            md_lines.append("")

        return "\n".join(md_lines)
