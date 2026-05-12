"""Immutable data models for the brief review pipeline.

All models are frozen pydantic models. Checkers must NEVER mutate inputs;
they return new `Finding` objects that the aggregator combines into a
`ReviewReport`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FindingColumn = Literal["formatting", "section"]


SECTION_TEMPLATE: tuple[tuple[str, str], ...] = (
    ("01_header_icon", "Financial Institution Icon"),
    ("02_title", "Document Title"),
    ("03_client_name_type", "Client Name & Type"),
    ("04_meeting_objective", "Meeting Objective"),
    ("05_client_markets", "Client Market(s)"),
    ("06_client_share", "Client Share in Market"),
    ("07_current_business", "Our Current Business"),
    ("08_key_facts", "What are the key facts about the client?"),
    ("09_exec_messages", "What are the 3-5 messages you want the executive to raise?"),
    ("10_client_topics", "Any issues or topics that the client will likely raise?"),
    ("11_meeting_with", "Who am I meeting with?"),
    ("12_vertex_attendees", "Who is joining me from Vertex?"),
)
"""Canonical (id, display_title) pairs in template order. The output table
always has exactly these 12 rows in this order."""


SECTION_IDS: tuple[str, ...] = tuple(s[0] for s in SECTION_TEMPLATE)


class Frozen(BaseModel):
    """Base for immutable models."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ImageRef(Frozen):
    """Reference to an image in the docx (header icon, photo, etc.)."""

    location: Literal["header", "body", "table_cell"]
    width_emu: int | None = None
    height_emu: int | None = None
    alt_text: str | None = None
    relation_id: str | None = None


class ParsedTable(Frozen):
    """Lightweight representation of a docx table.

    `cells` is a 2D list of plain text strings. Column count derived from
    the first row.
    """

    rows: tuple[tuple[str, ...], ...]
    has_images: bool = False

    @property
    def num_rows(self) -> int:
        return len(self.rows)

    @property
    def num_cols(self) -> int:
        if not self.rows:
            return 0
        return len(self.rows[0])


class Section(Frozen):
    """One section of the brief (template-aligned)."""

    id: str
    title: str
    order: int
    present: bool
    raw_text: str = ""
    bullets: tuple[str, ...] = ()
    tables: tuple[ParsedTable, ...] = ()
    images: tuple[ImageRef, ...] = ()


class Brief(Frozen):
    """Parsed brief document."""

    client_name: str | None
    title_text: str | None
    header_images: tuple[ImageRef, ...]
    sections: tuple[Section, ...]
    full_text: str

    def section(self, section_id: str) -> Section | None:
        for s in self.sections:
            if s.id == section_id:
                return s
        return None


class Finding(Frozen):
    """One piece of feedback to render in the output table."""

    section_id: str
    column: FindingColumn
    rule_id: str
    message: str
    evidence: str | None = None


class SectionReport(Frozen):
    """Per-section bucket of findings, in template order."""

    section_id: str
    title: str
    present: bool
    formatting_findings: tuple[Finding, ...] = Field(default_factory=tuple)
    section_findings: tuple[Finding, ...] = Field(default_factory=tuple)


class ReviewReport(Frozen):
    """Final aggregated report. Always has all 12 sections in order."""

    client_name: str | None
    rows: tuple[SectionReport, ...]
