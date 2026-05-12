"""Parser tests against the synthetic fixtures."""

from __future__ import annotations

from core.docx_parser import parse_brief
from core.models import SECTION_IDS, Brief


def test_parses_all_12_sections(clean_brief: Brief) -> None:
    assert len(clean_brief.sections) == 12
    assert tuple(s.id for s in clean_brief.sections) == SECTION_IDS


def test_sections_are_present_in_clean_brief(clean_brief: Brief) -> None:
    assert all(s.present for s in clean_brief.sections)


def test_extracts_client_name_and_title(clean_brief: Brief) -> None:
    assert clean_brief.client_name == "Acme Bank"
    assert clean_brief.title_text == "Acme Bank Meeting Brief"


def test_header_image_detected(clean_brief: Brief) -> None:
    assert len(clean_brief.header_images) == 1
    assert clean_brief.header_images[0].location == "header"


def test_two_column_tables_have_two_columns(clean_brief: Brief) -> None:
    for sid in (
        "03_client_name_type",
        "04_meeting_objective",
        "05_client_markets",
        "06_client_share",
        "07_current_business",
    ):
        section = clean_brief.section(sid)
        assert section is not None and section.tables
        assert section.tables[0].num_cols == 2


def test_attendee_table_is_4_columns(clean_brief: Brief) -> None:
    section = clean_brief.section("11_meeting_with")
    assert section is not None
    assert section.tables[0].num_cols == 4


def test_bullets_detected_in_exec_messages(clean_brief: Brief) -> None:
    section = clean_brief.section("09_exec_messages")
    assert section is not None
    assert len(section.bullets) >= 3


def test_missing_section_marked_not_present() -> None:
    from io import BytesIO

    from docx import Document

    doc = Document()
    doc.add_paragraph("Stub Co Meeting Brief")
    doc.add_paragraph("Client Name & Type")
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Client"
    table.rows[0].cells[1].text = "Stub Co, issuer"
    buf = BytesIO()
    doc.save(buf)

    brief = parse_brief(buf.getvalue())
    assert brief.section("12_vertex_attendees") is not None
    assert brief.section("12_vertex_attendees").present is False
