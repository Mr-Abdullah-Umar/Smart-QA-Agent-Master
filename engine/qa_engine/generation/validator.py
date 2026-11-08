"""Static AST security validation pipeline for AI-generated test scripts.

Enforces T2 controls & Section 8.7 specifications:
- Scripts must parse with Python ast.
- Strict import allowlist: pytest, playwright, re, json, datetime, math, typing, and local pages.
- Banned constructs: no eval, exec, subprocess, os, socket, outbound HTTP, ctypes, pickle.
- Bans time.sleep to enforce web-first auto-waiting assertions.
- Traceability: verifies every test function maps to an approved test case ID.
"""

import ast
import re
from typing import List, Optional, Set, Tuple

from pydantic import BaseModel, Field

ALLOWED_MODULES: Set[str] = {
    "pytest",
    "playwright",
    "playwright.sync_api",
    "playwright.async_api",
    "re",
    "json",
    "datetime",
    "math",
    "typing",
}

BANNED_FUNCTIONS: Set[str] = {
    "eval",
    "exec",
    "__import__",
    "compile",
    "globals",
    "locals",
    "getattr",
    "setattr",
    "delattr",
    "open",
    "input",
    "breakpoint",
}

BANNED_MODULE_PREFIXES: Tuple[str, ...] = (
    "os",
    "sys",
    "subprocess",
    "socket",
    "requests",
    "urllib.request",
    "http.client",
    "shutil",
    "ctypes",
    "pickle",
    "builtins",
)


class ScriptValidationError(Exception):
    """Raised when generated script violates security, import, or safety policies."""

    pass


class ASTSecurityVisitor(ast.NodeVisitor):
    """Walks the AST of generated code to detect banned imports, calls, or sleep statements."""

    def __init__(self):
        self.errors: List[str] = []
        self.discovered_tc_marks: Set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.name
            if not self._is_module_allowed(name):
                self.errors.append(f"Line {node.lineno}: Prohibited import '{name}'.")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod_name = node.module or ""
        # Allow relative/local imports from pages package
        if mod_name.startswith("pages") or node.level > 0:
            self.generic_visit(node)
            return

        if not self._is_module_allowed(mod_name):
            self.errors.append(f"Line {node.lineno}: Prohibited from-import '{mod_name}'.")
        self.generic_visit(node)

    def _is_module_allowed(self, mod_name: str) -> bool:
        if any(mod_name == b or mod_name.startswith(b + ".") for b in BANNED_MODULE_PREFIXES):
            return False
        if any(mod_name == a or mod_name.startswith(a + ".") for a in ALLOWED_MODULES):
            return True
        return False

    def visit_Call(self, node: ast.Call) -> None:
        # Check direct function calls: eval(), exec(), etc.
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name in BANNED_FUNCTIONS:
                self.errors.append(f"Line {node.lineno}: Prohibited function call '{func_name}()'.")

        # Check attribute calls: time.sleep(), os.system(), subprocess.run()
        elif isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            if attr_name == "sleep":
                self.errors.append(
                    f"Line {node.lineno}: 'time.sleep()' is banned. "
                    "Use web-first Playwright assertions instead."
                )
            if attr_name in ("system", "popen", "spawn", "execv", "execve"):
                self.errors.append(
                    f"Line {node.lineno}: Prohibited OS execution call '{attr_name}()'."
                )

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Enforce that every test_* function has @pytest.mark.tc("TC-ID")
        if node.name.startswith("test_"):
            has_tc_mark = False
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call):
                    # match pytest.mark.tc(...)
                    if isinstance(decorator.func, ast.Attribute) and decorator.func.attr == "tc":
                        if decorator.args and isinstance(decorator.args[0], ast.Constant):
                            self.discovered_tc_marks.add(str(decorator.args[0].value))
                            has_tc_mark = True
            if not has_tc_mark:
                self.errors.append(
                    f"Line {node.lineno}: Test function '{node.name}' "
                    "is missing @pytest.mark.tc('TC-ID') marker."
                )
        self.generic_visit(node)


class ValidationResult(BaseModel):
    is_valid: bool
    errors: List[str] = Field(default_factory=list)


class ScriptValidator:
    """Validates generated Python test scripts before allowing execution."""

    SUSPICIOUS_SECRET_PATTERNS = re.compile(
        r'(?i)(?:password|secret|api[_-]?key)\s*=\s*["\'](?!\{\{)[^"\']{8,}["\']'
    )

    @classmethod
    def validate_script(
        cls,
        code: str,
        approved_tc_ids: Optional[Set[str]] = None,
    ) -> ValidationResult:
        """Validate script returning structured ValidationResult."""
        is_valid, errors = cls.validate_code(code, approved_tc_ids)
        return ValidationResult(is_valid=is_valid, errors=errors)

    @classmethod
    def validate_code(
        cls,
        code: str,
        approved_tc_ids: Optional[Set[str]] = None,
    ) -> Tuple[bool, List[str]]:
        errors: List[str] = []

        # 1. Parse AST
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, [f"SyntaxError parsing generated script: {e}"]

        # 2. Walk AST for security policy violations
        visitor = ASTSecurityVisitor()
        visitor.visit(tree)
        errors.extend(visitor.errors)

        # 3. Check for hardcoded secret literals
        if cls.SUSPICIOUS_SECRET_PATTERNS.search(code):
            errors.append(
                "Detected possible hardcoded secret literal. Use harness fixtures instead."
            )

        # 4. Check Traceability: tests must map to approved test cases
        if approved_tc_ids is not None:
            unmapped = visitor.discovered_tc_marks - approved_tc_ids
            if unmapped:
                errors.append(f"Generated tests contain unapproved test case IDs: {unmapped}")

        return len(errors) == 0, errors


ASTSecurityValidator = ScriptValidator
