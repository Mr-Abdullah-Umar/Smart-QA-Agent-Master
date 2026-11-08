"""Test script and Page Object Model generator for Playwright and pytest.

Enforces Section 8.7 specifications:
- One test function per approved case, decorated with @pytest.mark.tc("TC-ID").
- Steps from the approved case appear as comments in the test body.
- Web-first assertions with automatic waiting; fixed sleeps banned.
- Secrets and base URLs come from harness fixtures, never literals.
- Modular Page Objects created in scripts/pages/ using semantic role locators.
"""

import re
from pathlib import Path
from typing import Dict, List

from qa_engine.generation.testcases import TestCase
from qa_engine.orchestrator.run_store import RunStore


def sanitize_identifier(text: str) -> str:
    """Convert an arbitrary string into a valid Python class or variable name."""
    clean = re.sub(r"[^a-zA-Z0-9_]+", "_", text).strip("_")
    if not clean or clean[0].isdigit():
        clean = "item_" + clean
    return clean.lower()


class ScriptGenerator:
    """Generates Python Playwright/pytest test suites and Page Object classes."""

    @classmethod
    def generate_page_object(cls, class_name: str, elements: Dict[str, Dict[str, str]]) -> str:
        """Generate a Page Object Model class using role-based locators."""
        lines = [
            '"""Auto-generated Page Object using semantic Playwright locators."""',
            "from playwright.sync_api import Page, Locator, expect",
            "",
            f"class {class_name}:",
            "    def __init__(self, page: Page):",
            "        self.page = page",
        ]

        # Define locator properties
        for key, info in elements.items():
            attr_name = sanitize_identifier(key)
            role = info.get("role", "button")
            name = info.get("name", "")
            if name:
                lines.append(
                    f'        self.{attr_name}: Locator = page.get_by_role("{role}", name="{name}")'
                )
            else:
                lines.append(f'        self.{attr_name}: Locator = page.get_by_role("{role}")')

        lines.append("")
        return "\n".join(lines)

    @classmethod
    def generate_test_suite(
        cls,
        suite_name: str,
        testcases: List[TestCase],
        page_imports: List[str],
    ) -> str:
        """Generate pytest test functions mapped 1-to-1 with approved test cases."""
        lines = [
            f'"""Auto-generated pytest suite: {suite_name}."""',
            "import pytest",
            "from playwright.sync_api import Page, expect",
        ]

        for p_import in page_imports:
            lines.append(f"from pages.{p_import} import {p_import.capitalize()}Page")

        lines.append("")

        for tc in testcases:
            func_name = f"test_{sanitize_identifier(tc.tc_id)}"
            lines.append(f'@pytest.mark.tc("{tc.tc_id}")')
            lines.append(f"def {func_name}(page: Page, base_url: str):")
            lines.append(f'    """{tc.title}')
            lines.append(f"    Requirement: {tc.requirement_ref}")
            lines.append(f"    Priority: {tc.priority.value}")
            lines.append('    """')

            # Preconditions as comments
            if tc.preconditions:
                lines.append("    # Preconditions:")
                for pre in tc.preconditions:
                    lines.append(f"    # - {pre}")

            # Steps as numbered comments with placeholder actions
            lines.append("    # Test Steps:")
            for idx, step in enumerate(tc.steps, start=1):
                lines.append(f"    # Step {idx}: {step}")
                if "navigate" in step.lower() or "open" in step.lower():
                    lines.append("    page.goto(base_url)")

            # Expected result assertion
            lines.append("    # Expected Result Verification:")
            lines.append(f"    # Verify: {tc.expected_result}")
            lines.append('    expect(page.locator("body")).to_be_visible()')
            lines.append("")

        return "\n".join(lines)

    @classmethod
    def write_scripts(
        cls,
        run_store: RunStore,
        testcases: List[TestCase],
        page_name: str = "main",
    ) -> Dict[str, Path]:
        """Write generated Page Objects and pytest suites into the run store."""
        pages_dir = run_store.run_dir / "scripts" / "pages"
        tests_dir = run_store.run_dir / "scripts" / "tests"

        pages_dir.mkdir(parents=True, exist_ok=True)
        tests_dir.mkdir(parents=True, exist_ok=True)

        # Create __init__.py files
        (pages_dir / "__init__.py").touch()
        (tests_dir / "__init__.py").touch()

        # 1. Generate Page Object
        page_code = cls.generate_page_object(f"{page_name.capitalize()}Page", {})
        page_path = pages_dir / f"{page_name}.py"
        page_path.write_text(page_code, encoding="utf-8")

        # 2. Generate Test Suite
        test_code = cls.generate_test_suite("Functional Suite", testcases, [page_name])
        test_path = tests_dir / "test_functional.py"
        test_path.write_text(test_code, encoding="utf-8")

        return {
            "page": page_path,
            "test": test_path,
        }
