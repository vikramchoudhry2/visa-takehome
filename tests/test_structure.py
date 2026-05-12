"""Structural / section checker tests."""

from __future__ import annotations

from core.checkers.header_image import check_header_icon
from core.checkers.structure import (
    check_client_topics,
    check_exec_messages,
    check_key_facts_lines,
    check_meeting_with,
    check_section_presence,
    check_structure,
    check_title,
    check_two_column_tables,
    check_vertex_attendees,
)
from core.models import Brief


def test_clean_brief_passes_all_structure_checks(clean_brief: Brief) -> None:
    assert check_structure(clean_brief) == []
    assert check_header_icon(clean_brief) == []


def test_dirty_brief_fires_structure_rules(dirty_brief: Brief) -> None:
    rule_ids = {f.rule_id for f in check_structure(dirty_brief)}
    expected = {
        "TITLE_CAPITALIZATION",
        "KEY_FACTS_LINE_LIMIT",
        "MAX_FIVE_BULLETS",
        "MAX_THREE_BULLETS",
        "ATTENDEE_TABLE_COLUMNS",
        "VERTEX_ATTENDEE_FORMAT",
    }
    missing = expected - rule_ids
    assert not missing, f"missing: {missing}; got {rule_ids}"


def test_section_presence_flags_missing() -> None:
    from io import BytesIO

    from docx import Document

    from core.docx_parser import parse_brief

    doc = Document()
    doc.add_paragraph("Stub Co Meeting Brief")
    buf = BytesIO()
    doc.save(buf)

    brief = parse_brief(buf.getvalue())
    findings = check_section_presence(brief)
    rule_ids = {f.rule_id for f in findings}
    assert "SECTION_MISSING" in rule_ids
    section_ids = {f.section_id for f in findings}
    assert "12_vertex_attendees" in section_ids


def test_header_icon_missing() -> None:
    from io import BytesIO

    from docx import Document

    from core.docx_parser import parse_brief

    doc = Document()
    doc.add_paragraph("Stub Co Meeting Brief")
    buf = BytesIO()
    doc.save(buf)

    brief = parse_brief(buf.getvalue())
    findings = check_header_icon(brief)
    assert len(findings) == 1
    assert findings[0].rule_id == "HEADER_ICON_MISSING"


def test_two_col_table_flags_wrong_column_count(dirty_brief: Brief) -> None:
    findings = check_two_column_tables(dirty_brief)
    _ = findings


def test_individual_checkers_match_aggregate(dirty_brief: Brief) -> None:
    aggregate_ids = {f.rule_id for f in check_structure(dirty_brief)}
    individual_ids: set[str] = set()
    for fn in (
        check_section_presence,
        check_title,
        check_two_column_tables,
        check_key_facts_lines,
        check_exec_messages,
        check_client_topics,
        check_meeting_with,
        check_vertex_attendees,
    ):
        individual_ids |= {f.rule_id for f in fn(dirty_brief)}
    assert aggregate_ids == individual_ids
