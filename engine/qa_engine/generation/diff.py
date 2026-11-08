"""Diff computation between iterative test case versions (v1 vs v2)."""

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from qa_engine.generation.testcases import TestCase, TestCaseCollection


class FieldChange(BaseModel):
    field_name: str
    old_value: Any
    new_value: Any


class TestCaseDiff(BaseModel):
    __test__ = False
    tc_id: str
    title: str
    changes: List[FieldChange] = Field(default_factory=list)


class VersionDiff(BaseModel):
    old_version: int
    new_version: int
    added_cases: List[TestCase] = Field(default_factory=list)
    removed_cases: List[TestCase] = Field(default_factory=list)
    modified_cases: List[TestCaseDiff] = Field(default_factory=list)
    total_changes: int = 0

    def generate_summary(self) -> str:
        parts = []
        if self.added_cases:
            parts.append(f"{len(self.added_cases)} added")
        if self.removed_cases:
            parts.append(f"{len(self.removed_cases)} removed")
        if self.modified_cases:
            parts.append(f"{len(self.modified_cases)} modified")
        return f"Version {self.old_version} -> {self.new_version}: " + (
            ", ".join(parts) if parts else "No changes"
        )


class TestCaseDiffEngine:
    """Computes semantic diffs between two collections of test cases."""

    @classmethod
    def compute_diff(
        cls, old_collection: TestCaseCollection, new_collection: TestCaseCollection
    ) -> VersionDiff:
        old_map: Dict[str, TestCase] = {tc.tc_id: tc for tc in old_collection.testcases}
        new_map: Dict[str, TestCase] = {tc.tc_id: tc for tc in new_collection.testcases}

        added: List[TestCase] = []
        removed: List[TestCase] = []
        modified: List[TestCaseDiff] = []

        # Find added
        for tc_id, tc in new_map.items():
            if tc_id not in old_map:
                added.append(tc)

        # Find removed
        for tc_id, tc in old_map.items():
            if tc_id not in new_map:
                removed.append(tc)

        # Find modified
        fields_to_compare = [
            "title",
            "category",
            "priority",
            "preconditions",
            "test_data",
            "steps",
            "expected_result",
            "postconditions",
            "automation_candidate",
        ]

        for tc_id, old_tc in old_map.items():
            if tc_id in new_map:
                new_tc = new_map[tc_id]
                field_changes: List[FieldChange] = []
                for f_name in fields_to_compare:
                    old_val = getattr(old_tc, f_name)
                    new_val = getattr(new_tc, f_name)
                    if old_val != new_val:
                        field_changes.append(
                            FieldChange(field_name=f_name, old_value=old_val, new_value=new_val)
                        )
                if field_changes:
                    modified.append(
                        TestCaseDiff(tc_id=tc_id, title=new_tc.title, changes=field_changes)
                    )

        total_changes = len(added) + len(removed) + len(modified)
        return VersionDiff(
            old_version=old_collection.version,
            new_version=new_collection.version,
            added_cases=added,
            removed_cases=removed,
            modified_cases=modified,
            total_changes=total_changes,
        )
