"""Site Profiler for storing and exporting application structure discovered during exploration.

Enforces Section 8.4:
Generates site-profile.json containing pages, URL patterns, forms, fields,
interactive widgets, console errors, and network anomalies.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from qa_engine.browser.snapshot import SnapshotResult


class DiscoveredField(BaseModel):
    ref_id: str
    role: str
    name: str
    value: Optional[str] = None
    is_required: bool = False
    field_type: str = "text"


class DiscoveredForm(BaseModel):
    form_name: str
    fields: List[DiscoveredField] = Field(default_factory=list)


class DiscoveredPage(BaseModel):
    url: str
    title: str
    interactive_elements_count: int
    forms: List[DiscoveredForm] = Field(default_factory=list)
    has_iframes: bool = False
    has_shadow_dom: bool = False


class SiteProfile(BaseModel):
    start_url: str
    allowed_domains: List[str]
    pages: List[DiscoveredPage] = Field(default_factory=list)
    console_errors: List[str] = Field(default_factory=list)
    failed_requests: List[Dict[str, Any]] = Field(default_factory=list)

    def add_page(
        self,
        snapshot: SnapshotResult,
        console_logs: Optional[List[Dict[str, str]]] = None,
        failed_requests: Optional[List[Dict[str, Any]]] = None,
    ) -> DiscoveredPage:
        # Group textboxes and buttons into a default form profile
        form_fields: List[DiscoveredField] = []
        for ref_id, el in snapshot.elements.items():
            if el.role in ("textbox", "checkbox", "radio", "combobox"):
                form_fields.append(
                    DiscoveredField(
                        ref_id=ref_id,
                        role=el.role,
                        name=el.name,
                        value=el.value,
                    )
                )

        forms = [DiscoveredForm(form_name="Main Form", fields=form_fields)] if form_fields else []

        page = DiscoveredPage(
            url=snapshot.url,
            title=snapshot.title,
            interactive_elements_count=snapshot.total_interactive_elements,
            forms=forms,
        )
        self.pages.append(page)

        # Ingest errors
        if console_logs:
            for log in console_logs:
                if log.get("type") in ("error", "warning"):
                    self.console_errors.append(f"[{log.get('type')}] {log.get('text')}")

        if failed_requests:
            self.failed_requests.extend(failed_requests)

        return page
