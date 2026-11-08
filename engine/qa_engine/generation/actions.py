"""Structured browser action plan attached to each test case.

The LLM (or the deterministic smoke designer) never writes Python. It emits a list of
validated `TestAction` objects; `render_action` turns each one into a single line of
Playwright code built only from escaped literals, so generated scripts stay inside the
AST security policy by construction.

Text values may contain placeholders resolved at run time by the harness conftest:
- `{{secret.NAME}}`  -> value of a secret stored in the VS Code keychain (never on disk)
- `{{unique}}`       -> a short unique token (for e.g. new-account emails)
"""

import json
import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

ARIA_ROLES = frozenset(
    {
        "alert",
        "alertdialog",
        "application",
        "article",
        "banner",
        "blockquote",
        "button",
        "caption",
        "cell",
        "checkbox",
        "code",
        "columnheader",
        "combobox",
        "complementary",
        "contentinfo",
        "definition",
        "deletion",
        "dialog",
        "directory",
        "document",
        "emphasis",
        "feed",
        "figure",
        "form",
        "generic",
        "grid",
        "gridcell",
        "group",
        "heading",
        "img",
        "insertion",
        "link",
        "list",
        "listbox",
        "listitem",
        "log",
        "main",
        "marquee",
        "math",
        "menu",
        "menubar",
        "menuitem",
        "menuitemcheckbox",
        "menuitemradio",
        "meter",
        "navigation",
        "none",
        "note",
        "option",
        "paragraph",
        "presentation",
        "progressbar",
        "radio",
        "radiogroup",
        "region",
        "row",
        "rowgroup",
        "rowheader",
        "scrollbar",
        "search",
        "searchbox",
        "separator",
        "slider",
        "spinbutton",
        "status",
        "strong",
        "subscript",
        "superscript",
        "switch",
        "tab",
        "table",
        "tablist",
        "tabpanel",
        "term",
        "textbox",
        "time",
        "timer",
        "toolbar",
        "tooltip",
        "tree",
        "treegrid",
        "treeitem",
    }
)

ActionType = Literal[
    "goto",
    "click",
    "fill",
    "select",
    "check",
    "uncheck",
    "press",
    "hover",
    "expect_visible",
    "expect_hidden",
    "expect_text",
    "expect_url",
    "expect_title",
    "expect_value",
    "expect_count",
    "expect_enabled",
    "expect_disabled",
    "expect_checked",
]

_NEEDS_TARGET = {
    "click",
    "fill",
    "select",
    "check",
    "uncheck",
    "hover",
    "expect_visible",
    "expect_hidden",
    "expect_value",
    "expect_count",
    "expect_enabled",
    "expect_disabled",
    "expect_checked",
}
_NEEDS_VALUE = {
    "fill",
    "select",
    "press",
    "expect_text",
    "expect_url",
    "expect_title",
    "expect_value",
    "expect_count",
}
_PLACEHOLDER = re.compile(r"\{\{\s*(secret\.[A-Za-z0-9_]+|unique)\s*\}\}")
SECRET_NAME = re.compile(r"\{\{\s*secret\.([A-Za-z0-9_]+)\s*\}\}")


class ElementLocator(BaseModel):
    """User-facing locator: ARIA role + accessible name, label, placeholder, text, or test id."""

    by: Literal["role", "label", "placeholder", "text", "test_id", "alt_text", "title"] = "role"
    role: Optional[str] = Field(default=None, description="ARIA role when by='role'")
    value: str = Field(default="", description="Accessible name / label / text to match")
    exact: bool = False
    nth: Optional[int] = Field(default=None, ge=0, description="0-based index if several match")

    @model_validator(mode="after")
    def _check(self) -> "ElementLocator":
        if self.by == "role":
            self.role = (self.role or "").strip().lower()
            if self.role not in ARIA_ROLES:
                raise ValueError(f"Unknown ARIA role '{self.role}'.")
        elif not self.value.strip():
            raise ValueError(f"Locator by '{self.by}' needs a non-empty value.")
        return self


class TestAction(BaseModel):
    __test__ = False
    action: ActionType
    target: Optional[ElementLocator] = None
    value: Optional[str] = None
    description: Optional[str] = None

    @model_validator(mode="after")
    def _check(self) -> "TestAction":
        if self.action in _NEEDS_TARGET and self.target is None:
            raise ValueError(f"Action '{self.action}' requires a target locator.")
        if self.action in _NEEDS_VALUE and (self.value is None or self.value == ""):
            raise ValueError(f"Action '{self.action}' requires a value.")
        if self.action == "expect_count":
            try:
                int(str(self.value))
            except ValueError as exc:
                raise ValueError("expect_count value must be an integer.") from exc
        return self

    @field_validator("value", mode="before")
    @classmethod
    def _stringify(cls, value):
        return None if value is None else str(value)


def secret_names(actions: List[TestAction]) -> List[str]:
    names = {m.upper() for action in actions for m in SECRET_NAME.findall(action.value or "")}
    return sorted(names)


def _lit(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _text(value: str) -> str:
    """Literal string, or a runtime placeholder expansion through the harness fixture."""
    return f"harness_text({_lit(value)})" if _PLACEHOLDER.search(value) else _lit(value)


def locator_expr(loc: ElementLocator, single: bool = True) -> str:
    exact = ", exact=True" if loc.exact else ""
    if loc.by == "role":
        name = f", name={_lit(loc.value)}" if loc.value else ""
        expr = f"page.get_by_role({_lit(loc.role or 'generic')}{name}{exact})"
    elif loc.by == "test_id":
        expr = f"page.get_by_test_id({_lit(loc.value)})"
    else:
        expr = f"page.get_by_{loc.by}({_lit(loc.value)}{exact})"
    if loc.nth is not None:
        return f"{expr}.nth({loc.nth})"
    return f"{expr}.first" if single else expr


def render_action(action: TestAction) -> str:
    """Return one Python statement implementing the action (no leading indentation)."""
    a, v = action.action, action.value or ""
    loc = locator_expr(action.target) if action.target else ""
    if a == "goto":
        return f"page.goto(harness_url({_lit(v)}))"
    if a == "click":
        return f"{loc}.click()"
    if a == "fill":
        return f"{loc}.fill({_text(v)})"
    if a == "select":
        return f"{loc}.select_option({_text(v)})"
    if a == "check":
        return f"{loc}.check()"
    if a == "uncheck":
        return f"{loc}.uncheck()"
    if a == "hover":
        return f"{loc}.hover()"
    if a == "press":
        return f"{loc}.press({_lit(v)})" if loc else f"page.keyboard.press({_lit(v)})"
    if a == "expect_visible":
        return f"expect({loc}).to_be_visible()"
    if a == "expect_hidden":
        return f"expect({loc}).to_be_hidden()"
    if a == "expect_text":
        target = loc or 'page.locator("body")'
        return f"expect({target}).to_contain_text({_text(v)})"
    if a == "expect_url":
        return f"expect(page).to_have_url(re.compile(re.escape(harness_url.match({_lit(v)}))))"
    if a == "expect_title":
        return f"expect(page).to_have_title(re.compile(re.escape({_lit(v)})))"
    if a == "expect_value":
        return f"expect({loc}).to_have_value({_text(v)})"
    if a == "expect_count":
        assert action.target is not None
        return f"expect({locator_expr(action.target, single=False)}).to_have_count({int(v)})"
    if a == "expect_enabled":
        return f"expect({loc}).to_be_enabled()"
    if a == "expect_disabled":
        return f"expect({loc}).to_be_disabled()"
    if a == "expect_checked":
        return f"expect({loc}).to_be_checked()"
    raise ValueError(f"Unsupported action '{a}'")


def expand_placeholders(text: str, secrets: Dict[str, str], unique: str) -> Optional[str]:
    """Runtime expansion used by the dry run; None when a referenced secret is missing."""
    missing: List[str] = []

    def repl(match: "re.Match[str]") -> str:
        placeholder = match.group(1)
        if placeholder == "unique":
            return unique
        name = placeholder.split(".", 1)[1].upper()
        if name not in secrets:
            missing.append(name)
            return ""
        return secrets[name]

    expanded = _PLACEHOLDER.sub(repl, text)
    return None if missing else expanded


def build_locator(page: Any, loc: ElementLocator, single: bool = True) -> Any:
    """Playwright locator equivalent to `locator_expr` (same semantics as generated code)."""
    if loc.by == "role":
        kwargs: Dict[str, Any] = {"name": loc.value} if loc.value else {}
        if loc.exact:
            kwargs["exact"] = True
        locator = page.get_by_role(loc.role or "generic", **kwargs)
    elif loc.by == "test_id":
        locator = page.get_by_test_id(loc.value)
    else:
        locator = getattr(page, f"get_by_{loc.by}")(loc.value, exact=loc.exact)
    if loc.nth is not None:
        return locator.nth(loc.nth)
    return locator.first if single else locator


def describe_action(action: TestAction) -> str:
    """Short human-readable rendering for review cards and Markdown."""
    if action.description:
        return action.description
    target = ""
    if action.target:
        t = action.target
        target = f"{t.role} '{t.value}'" if t.by == "role" else f"{t.by} '{t.value}'"
    value = f" = '{action.value}'" if action.value else ""
    return f"{action.action} {target}{value}".strip()
