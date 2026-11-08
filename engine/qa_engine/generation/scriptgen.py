"""Test script and Page Object Model generator for Playwright and pytest.

Enforces Section 8.7 specifications:
- One test function per approved case, decorated with @pytest.mark.tc("TC-ID").
- Steps from the approved case appear as comments in the test body.
- Web-first assertions with automatic waiting; fixed sleeps banned.
- Secrets and base URLs come from harness fixtures, never literals.
- Modular Page Objects created in scripts/pages/ using semantic role locators.

Code is compiled deterministically from each case's validated action plan; nothing the
model writes is executed verbatim.
"""

import json
import re
from pathlib import Path
from typing import Dict, List

from qa_engine.generation.actions import describe_action, locator_expr, render_action
from qa_engine.generation.testcases import TestCase


def sanitize_identifier(text: str) -> str:
    """Convert an arbitrary string into a valid Python class or variable name."""
    clean = re.sub(r"[^a-zA-Z0-9_]+", "_", text).strip("_")
    if not clean or clean[0].isdigit():
        clean = "item_" + clean
    return clean.lower()


def test_function_name(tc_id: str) -> str:
    return f"test_{sanitize_identifier(tc_id)}"


def _py_str(value: str) -> str:
    """Render a string as a safely escaped Python literal (JSON strings are valid Python)."""
    return json.dumps(value, ensure_ascii=False)


def _single_line(text: str) -> str:
    return " ".join(str(text).split())


def _comment(text: str) -> str:
    return _single_line(text).replace("\\", "/")


def _role_locator(test_data: Dict[str, str]) -> str:
    role = _py_str(test_data.get("role", "button"))
    name = test_data.get("name", "")
    if name:
        expr = f"page.get_by_role({role}, name={_py_str(name)}, exact=True)"
    else:
        expr = f"page.get_by_role({role})"
    return f"{expr}.first"


class ScriptGenerator:
    """Generates Python Playwright/pytest test suites and Page Object classes."""

    @classmethod
    def generate_page_object(cls, class_name: str, testcases: List[TestCase]) -> str:
        """Page Object exposing every distinct locator used by the suite's action plans."""
        lines = [
            '"""Auto-generated Page Object using semantic Playwright locators."""',
            "from playwright.sync_api import Locator, Page",
            "",
            "",
            f"class {class_name}:",
            "    def __init__(self, page: Page):",
            "        self.page = page",
        ]
        seen: Dict[str, str] = {}
        for tc in testcases:
            for action in tc.actions:
                if not action.target:
                    continue
                expr = locator_expr(action.target)
                if expr in seen.values():
                    continue
                base = sanitize_identifier(
                    f"{action.target.role or action.target.by}_{action.target.value}"
                )[:48]
                attr, n = base, 2
                while attr in seen:
                    attr, n = f"{base}_{n}", n + 1
                seen[attr] = expr
        for attr, expr in seen.items():
            lines.append(f"        self.{attr}: Locator = {expr}")
        lines.append("")
        return "\n".join(lines)

    @classmethod
    def generate_test_suite(cls, suite_name: str, testcases: List[TestCase]) -> str:
        """Generate pytest test functions mapped 1-to-1 with approved test cases."""
        lines = [
            f'"""Auto-generated pytest suite: {_comment(suite_name)}."""',
            "import re",
            "",
            "import pytest",
            "from playwright.sync_api import Page, expect",
            "",
        ]

        for tc in testcases:
            docstring = _single_line(tc.title).replace("\\", "/").replace('"', "'")
            lines.append("")
            lines.append(f"@pytest.mark.tc({_py_str(tc.tc_id)})")
            for test_type in tc.test_types:
                lines.append(f"@pytest.mark.{test_type}")
            lines.append(
                f"def {test_function_name(tc.tc_id)}(page: Page, harness_url, harness_text):"
            )
            lines.append(f'    """{docstring}')
            lines.append(f"    Requirement: {_comment(tc.requirement_ref)}")
            if tc.ac_ref:
                lines.append(f"    Acceptance criterion: {_comment(tc.ac_ref)}")
            lines.append(f"    Priority: {tc.priority.value}")
            lines.append('    """')

            if tc.preconditions:
                lines.append("    # Preconditions:")
                for pre in tc.preconditions:
                    lines.append(f"    # - {_comment(pre)}")
            lines.append("    # Test Steps:")
            for idx, step in enumerate(tc.steps, start=1):
                lines.append(f"    # Step {idx}: {_comment(step)}")
            lines.append(f"    # Expected: {_comment(tc.expected_result)}")

            if not tc.actions or tc.actions[0].action != "goto":
                lines.append('    page.goto(harness_url(""))')
            if tc.actions:
                for action in tc.actions:
                    lines.append(f"    # {_comment(describe_action(action))}")
                    lines.append(f"    {render_action(action)}")
            else:
                lines.extend(cls._legacy_assertion_lines(tc))

        lines.append("")
        return "\n".join(lines)

    @classmethod
    def _legacy_assertion_lines(cls, tc: TestCase) -> List[str]:
        """Assertions for cases drafted before action plans existed (test_data['check'])."""
        data = tc.test_data or {}
        check = data.get("check")
        if check == "title":
            return [f"    expect(page).to_have_title({_py_str(data.get('expected', ''))})"]
        if check == "visible":
            return [f"    expect({_role_locator(data)}).to_be_visible()"]
        if check == "fillable":
            value = _py_str(data.get("value", "qa-harness-sample"))
            return [
                f"    {_role_locator(data)}.fill({value})",
                f"    expect({_role_locator(data)}).to_have_value({value})",
            ]
        return ['    expect(page.locator("body")).to_be_visible()']

    @classmethod
    def write_scripts(
        cls, scripts_dir: Path, testcases: List[TestCase], module_name: str
    ) -> Dict[str, Path]:
        """Write the Page Object and pytest suite for one module into `scripts_dir`."""
        slug = sanitize_identifier(module_name)
        pages_dir = scripts_dir / "pages"
        tests_dir = scripts_dir / "tests"
        pages_dir.mkdir(parents=True, exist_ok=True)
        tests_dir.mkdir(parents=True, exist_ok=True)
        (pages_dir / "__init__.py").touch()
        (tests_dir / "__init__.py").touch()

        class_name = "".join(part.capitalize() for part in slug.split("_")) + "Page"
        page_path = pages_dir / f"{slug}_page.py"
        page_path.write_text(cls.generate_page_object(class_name, testcases), encoding="utf-8")

        test_path = tests_dir / f"test_{slug}.py"
        test_path.write_text(cls.generate_test_suite(module_name, testcases), encoding="utf-8")
        return {"page": page_path, "test": test_path}
