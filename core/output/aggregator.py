"""Aggregate raw findings into the per-section `ReviewReport`.

Always emits all 15 sections in template order, even when no findings
exist for that section, so the output table has consistent shape.
"""

from __future__ import annotations

from collections.abc import Iterable

from core.models import (
    SECTION_TEMPLATE,
    Brief,
    Finding,
    ReviewReport,
    SectionReport,
)


def aggregate(brief: Brief, findings: Iterable[Finding]) -> ReviewReport:
    by_section_formatting: dict[str, list[Finding]] = {sid: [] for sid, _ in SECTION_TEMPLATE}
    by_section_section: dict[str, list[Finding]] = {sid: [] for sid, _ in SECTION_TEMPLATE}

    seen: set[tuple[str, str, str, str]] = set()
    for f in findings:
        key = (f.section_id, f.column, f.rule_id, f.message)
        if key in seen:
            continue
        seen.add(key)
        target = by_section_formatting if f.column == "formatting" else by_section_section
        bucket = target.setdefault(f.section_id, [])
        bucket.append(f)

    rows: list[SectionReport] = []
    for sid, display_title in SECTION_TEMPLATE:
        section = brief.section(sid)
        present = bool(section and section.present)
        rows.append(
            SectionReport(
                section_id=sid,
                title=display_title,
                present=present,
                formatting_findings=tuple(by_section_formatting.get(sid, [])),
                section_findings=tuple(by_section_section.get(sid, [])),
            )
        )

    return ReviewReport(client_name=brief.client_name, rows=tuple(rows))
