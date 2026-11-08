"""Semantic ARIA accessibility tree snapshot generator and reference mapping.

Enforces Section 8.4 design:
- Produces a compact, role-based textual representation of the page.
- Assigns index references ([#1], [#2]) to interactive elements.
- Maps references back to deterministic Playwright role-and-name locators.
- Strips PII/tokens via RedactionEngine and caps output size.
"""

import re
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from qa_engine.security.redaction import RedactionEngine

INTERACTIVE_ROLES = {
    "button",
    "link",
    "textbox",
    "checkbox",
    "radio",
    "combobox",
    "listbox",
    "option",
    "tab",
    "menuitem",
    "searchbox",
    "switch",
    "slider",
    "treeitem",
}

YAML_LINE_PATTERN = re.compile(r'^(\s*)-\s+([a-zA-Z0-9_-]+)(?:\s+"([^"]*)")?(?:\s+\[(.*)\])?')


class ElementReference(BaseModel):
    ref_id: str  # e.g. "#1"
    role: str  # e.g. "button"
    name: str  # e.g. "Sign In"
    value: Optional[str] = None
    description: Optional[str] = None
    checked: Optional[bool] = None
    disabled: Optional[bool] = None
    expanded: Optional[bool] = None
    nth: int = 0  # Disambiguation index if multiple elements have same role & name


class SnapshotResult(BaseModel):
    url: str
    title: str
    text_representation: str
    elements: Dict[str, ElementReference] = Field(default_factory=dict)
    total_interactive_elements: int = 0


class AriaSnapshotExtractor:
    """Traverses Playwright accessibility trees and creates reference-indexed snapshots."""

    MAX_TREE_CHARS = 25000  # Cap size to prevent prompt bloating

    @classmethod
    def build_snapshot_from_yaml(
        cls,
        yaml_text: str,
        url: str,
        title: str,
    ) -> SnapshotResult:
        if not yaml_text or not yaml_text.strip():
            return SnapshotResult(
                url=url,
                title=title,
                text_representation="[Empty page or inaccessible tree]",
                elements={},
            )

        elements: Dict[str, ElementReference] = {}
        lines: List[str] = []
        name_counters: Dict[str, int] = {}
        ref_counter = 1

        for line in yaml_text.strip().split("\n"):
            m = YAML_LINE_PATTERN.match(line)
            if not m:
                lines.append(line)
                continue

            indent = m.group(1)
            role = m.group(2)
            name = m.group(3) or ""
            attrs_str = m.group(4) or ""

            is_interactive = role.lower() in INTERACTIVE_ROLES
            if is_interactive:
                ref_id = f"#{ref_counter}"
                ref_counter += 1

                sig = f"{role}:{name}"
                current_nth = name_counters.get(sig, 0)
                name_counters[sig] = current_nth + 1

                disabled = "disabled" in attrs_str.lower()
                checked = "checked" in attrs_str.lower()
                expanded = (
                    "expanded" in attrs_str.lower() if "expanded" in attrs_str.lower() else None
                )

                ref_obj = ElementReference(
                    ref_id=ref_id,
                    role=role,
                    name=name,
                    disabled=disabled if disabled else None,
                    checked=checked if checked else None,
                    expanded=expanded,
                    nth=current_nth,
                )
                elements[ref_id] = ref_obj

                attr_part = f" [{attrs_str}]" if attrs_str else ""
                lines.append(f'{indent}- {role} "{name}"{attr_part} [{ref_id}]')
            else:
                lines.append(line)

        raw_text = "\n".join(lines)
        if len(raw_text) > cls.MAX_TREE_CHARS:
            raw_text = (
                raw_text[: cls.MAX_TREE_CHARS] + "\n... [ARIA tree truncated due to size limit]"
            )

        cleaned_text, _ = RedactionEngine.redact(raw_text)

        return SnapshotResult(
            url=url,
            title=title,
            text_representation=cleaned_text,
            elements=elements,
            total_interactive_elements=len(elements),
        )

    @classmethod
    def build_snapshot(
        cls,
        ax_root: Optional[Union[str, Dict[str, Any]]],
        url: str,
        title: str,
    ) -> SnapshotResult:
        if isinstance(ax_root, str):
            return cls.build_snapshot_from_yaml(ax_root, url, title)

        if not ax_root:
            return SnapshotResult(
                url=url,
                title=title,
                text_representation="[Empty page or inaccessible tree]",
                elements={},
            )

        elements: Dict[str, ElementReference] = {}
        lines: List[str] = []
        name_counters: Dict[str, int] = {}
        ref_counter = 1

        def traverse(node: Dict[str, Any], depth: int = 0) -> None:
            nonlocal ref_counter

            role = node.get("role", "")
            name = node.get("name", "").strip()
            value = node.get("value")
            disabled = node.get("disabled")
            checked = node.get("checked")
            expanded = node.get("expanded")

            indent = "  " * depth
            is_interactive = role.lower() in INTERACTIVE_ROLES

            ref_tag = ""
            if is_interactive:
                ref_id = f"#{ref_counter}"
                ref_counter += 1

                sig = f"{role}:{name}"
                current_nth = name_counters.get(sig, 0)
                name_counters[sig] = current_nth + 1

                ref_obj = ElementReference(
                    ref_id=ref_id,
                    role=role,
                    name=name,
                    value=str(value) if value is not None else None,
                    disabled=disabled,
                    checked=checked,
                    expanded=expanded,
                    nth=current_nth,
                )
                elements[ref_id] = ref_obj
                ref_tag = f" [{ref_id}]"

            state_tokens = []
            if disabled:
                state_tokens.append("disabled")
            if checked:
                state_tokens.append("checked")
            if expanded is not None:
                state_tokens.append("expanded" if expanded else "collapsed")
            if value:
                state_tokens.append(f'value="{value}"')

            state_str = f" ({', '.join(state_tokens)})" if state_tokens else ""
            line = f'{indent}- {role} "{name}"{state_str}{ref_tag}'
            lines.append(line)

            for child in node.get("children", []):
                traverse(child, depth + 1)

        traverse(ax_root, depth=0)
        raw_text = "\n".join(lines)

        if len(raw_text) > cls.MAX_TREE_CHARS:
            raw_text = (
                raw_text[: cls.MAX_TREE_CHARS] + "\n... [ARIA tree truncated due to size limit]"
            )

        cleaned_text, _ = RedactionEngine.redact(raw_text)

        return SnapshotResult(
            url=url,
            title=title,
            text_representation=cleaned_text,
            elements=elements,
            total_interactive_elements=len(elements),
        )
