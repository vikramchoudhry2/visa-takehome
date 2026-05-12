"""Structural / section-level deterministic checkers (rules B.2 - B.12).

Every check returns `Finding` objects with `column="section"`. Findings
about missing sections are produced by `check_section_presence`; the
other checkers each focus on one or two sections.

Line counts in Word are technically rendering-dependent. We approximate
"lines" as the count of soft-wrapped lines using a fixed character
budget (~95 chars per body line) plus explicit newlines. This is
documented and surfaced in the finding text so the reviewer can sanity
check.
"""

from __future__ import annotations

import re

from core.models import SECTION_TEMPLATE, Brief, Finding, Section

CHARS_PER_LINE = 95


def check_structure(brief: Brief) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(check_section_presence(brief))
    findings.extend(check_title(brief))
    findings.extend(check_two_column_tables(brief))
    findings.extend(check_one_line_sections(brief))
    findings.extend(check_two_line_sections(brief))
    findings.extend(check_key_facts_lines(brief))
    findings.extend(check_exec_messages(brief))
    findings.extend(check_client_topics(brief))
    findings.extend(check_meeting_with(brief))
    findings.extend(check_vertex_attendees(brief))
    return findings


def check_section_presence(brief: Brief) -> list[Finding]:
    findings: list[Finding] = []
    for sid, display_title in SECTION_TEMPLATE:
        section = brief.section(sid)
        if section is None or not section.present:
            findings.append(
                Finding(
                    section_id=sid,
                    column="section",
                    rule_id="SECTION_MISSING",
                    message=f'Section "{display_title}" is missing from the brief.',
                )
            )
    return findings


_TITLE_RE = re.compile(r"^[A-Z][A-Za-z0-9&'.\-]*(?:\s+[A-Z][A-Za-z0-9&'.\-]*)*\s+Meeting Brief$")


def check_title(brief: Brief) -> list[Finding]:
    section = brief.section("02_title")
    if section is None or not section.present:
        return []
    title = section.raw_text.strip()
    if not title:
        return []
    findings: list[Finding] = []
    if not title.lower().endswith("meeting brief"):
        findings.append(
            Finding(
                section_id="02_title",
                column="section",
                rule_id="TITLE_FORMAT",
                message='Title must end with "Meeting Brief".',
                evidence=title,
            )
        )
        return findings
    if not _TITLE_RE.match(title):
        findings.append(
            Finding(
                section_id="02_title",
                column="section",
                rule_id="TITLE_CAPITALIZATION",
                message=(
                    'Title must be exactly "[Client Name] Meeting Brief" with the '
                    "first letter of each word capitalized."
                ),
                evidence=title,
            )
        )
    return findings


_TWO_COL_SECTIONS = (
    ("03_client_name_type", "Client Name & Type"),
    ("04_meeting_objective", "Meeting Objective"),
    ("05_client_markets", "Client Market(s)"),
    ("06_client_share", "Client Share in Market"),
    ("07_current_business", "Our Current Business"),
)


def check_two_column_tables(brief: Brief) -> list[Finding]:
    findings: list[Finding] = []
    for sid, display in _TWO_COL_SECTIONS:
        section = brief.section(sid)
        if section is None or not section.present:
            continue
        if not section.tables:
            findings.append(
                Finding(
                    section_id=sid,
                    column="section",
                    rule_id="TABLE_MISSING",
                    message=f"{display} must appear in a 2-column table.",
                )
            )
            continue
        first = section.tables[0]
        if first.num_cols != 2:
            findings.append(
                Finding(
                    section_id=sid,
                    column="section",
                    rule_id="TABLE_COLUMN_COUNT",
                    message=(
                        f"{display} table must have exactly 2 columns "
                        f"(found {first.num_cols})."
                    ),
                )
            )
    return findings


_ONE_LINE_SECTIONS = (
    ("03_client_name_type", "Client Name & Type"),
    ("04_meeting_objective", "Meeting Objective"),
)


def check_one_line_sections(brief: Brief) -> list[Finding]:
    findings: list[Finding] = []
    for sid, display in _ONE_LINE_SECTIONS:
        section = brief.section(sid)
        if section is None or not section.present:
            continue
        value_text = _value_cell_text(section)
        lines = _count_lines(value_text)
        if lines > 1:
            findings.append(
                Finding(
                    section_id=sid,
                    column="section",
                    rule_id="MAX_ONE_LINE",
                    message=(
                        f"{display} must be a maximum of 1 line "
                        f"(estimated {lines} based on ~{CHARS_PER_LINE} chars/line)."
                    ),
                    evidence=value_text[:120],
                )
            )
    return findings


_TWO_LINE_SECTIONS = (
    ("05_client_markets", "Client Market(s)"),
    ("06_client_share", "Client Share in Market"),
)


def check_two_line_sections(brief: Brief) -> list[Finding]:
    findings: list[Finding] = []
    for sid, display in _TWO_LINE_SECTIONS:
        section = brief.section(sid)
        if section is None or not section.present:
            continue
        value_text = _value_cell_text(section)
        lines = _count_lines(value_text)
        if lines > 2:
            findings.append(
                Finding(
                    section_id=sid,
                    column="section",
                    rule_id="MAX_TWO_LINES",
                    message=(
                        f"{display} must be a maximum of 2 lines "
                        f"(estimated {lines})."
                    ),
                    evidence=value_text[:200],
                )
            )
    return findings


_KEY_FACTS_LIMITS: tuple[tuple[str, str, int, bool], ...] = (
    ("business overview", "Business Overview", 3, True),
    ("competition", "Competition", 3, True),
    ("vertex overview", "Vertex Overview", 3, True),
    ("notable changes", "Notable Changes", 2, False),
)


def check_key_facts_lines(brief: Brief) -> list[Finding]:
    section = brief.section("08_key_facts")
    if section is None or not section.present:
        return []
    findings: list[Finding] = []
    paragraphs = [p for p in section.raw_text.split("\n") if p.strip()]
    for label, display, max_lines, required in _KEY_FACTS_LIMITS:
        body = _find_key_facts_paragraph(paragraphs, label)
        if body is None:
            if required:
                findings.append(
                    Finding(
                        section_id="08_key_facts",
                        column="section",
                        rule_id="KEY_FACTS_SUBSECTION_MISSING",
                        message=f'Key Facts subsection "{display}" is missing.',
                    )
                )
            continue
        lines = _count_lines(body)
        if lines > max_lines:
            findings.append(
                Finding(
                    section_id="08_key_facts",
                    column="section",
                    rule_id="KEY_FACTS_LINE_LIMIT",
                    message=(
                        f'"{display}" exceeds {max_lines} lines '
                        f"(estimated {lines})."
                    ),
                    evidence=body[:160],
                )
            )
    return findings


def _find_key_facts_paragraph(paragraphs: list[str], label: str) -> str | None:
    for p in paragraphs:
        first = p.split(":", 1)[0].strip().lower()
        if first == label:
            return p.split(":", 1)[1].strip() if ":" in p else p
    return None


def check_exec_messages(brief: Brief) -> list[Finding]:
    section = brief.section("09_exec_messages")
    if section is None or not section.present:
        return []
    findings: list[Finding] = []
    bullets = section.bullets
    if len(bullets) > 5:
        findings.append(
            Finding(
                section_id="09_exec_messages",
                column="section",
                rule_id="MAX_FIVE_BULLETS",
                message=f"Exceeds 5 bullets (found {len(bullets)}).",
            )
        )
    if not bullets:
        findings.append(
            Finding(
                section_id="09_exec_messages",
                column="section",
                rule_id="MISSING_BULLETS",
                message="Section must contain bulleted talking points (none found).",
            )
        )
    for i, bullet in enumerate(bullets, start=1):
        lines = _count_lines(bullet)
        if lines > 3:
            findings.append(
                Finding(
                    section_id="09_exec_messages",
                    column="section",
                    rule_id="BULLET_LINE_LIMIT",
                    message=f"Bullet {i} exceeds 3 lines (estimated {lines}).",
                    evidence=bullet[:160],
                )
            )
    return findings


def check_client_topics(brief: Brief) -> list[Finding]:
    section = brief.section("10_client_topics")
    if section is None or not section.present:
        return []
    findings: list[Finding] = []
    bullets = section.bullets
    if len(bullets) > 3:
        findings.append(
            Finding(
                section_id="10_client_topics",
                column="section",
                rule_id="MAX_THREE_BULLETS",
                message=f"Exceeds 3 bullets (found {len(bullets)}).",
            )
        )
    if not bullets:
        findings.append(
            Finding(
                section_id="10_client_topics",
                column="section",
                rule_id="MISSING_BULLETS",
                message="Section must contain bulleted topics (none found).",
            )
        )
    for i, bullet in enumerate(bullets, start=1):
        lines = _count_lines(bullet)
        if lines > 3:
            findings.append(
                Finding(
                    section_id="10_client_topics",
                    column="section",
                    rule_id="BULLET_LINE_LIMIT",
                    message=f"Bullet {i} exceeds 3 lines (estimated {lines}).",
                    evidence=bullet[:160],
                )
            )
    return findings


_NAME_REQUIRED_FIELDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Pronunciation", re.compile(r"\([A-Z][A-Z' \-]*\)")),
    ("Title", re.compile(r"\b(?:CEO|CFO|COO|CMO|CTO|President|VP|SVP|EVP|Director|Manager|Head|Chief|Officer|Lead|Partner)\b", re.IGNORECASE)),
    ("Form of address", re.compile(r"\b(Mr\.|Mrs\.|Ms\.|Dr\.|Mx\.)")),
    ("Email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
)


def check_meeting_with(brief: Brief) -> list[Finding]:
    section = brief.section("11_meeting_with")
    if section is None or not section.present:
        return []
    findings: list[Finding] = []
    if not section.tables:
        findings.append(
            Finding(
                section_id="11_meeting_with",
                column="section",
                rule_id="ATTENDEE_TABLE_MISSING",
                message='"Who am I meeting with?" must be a 4-column table.',
            )
        )
        return findings
    table = section.tables[0]
    if table.num_cols != 4:
        findings.append(
            Finding(
                section_id="11_meeting_with",
                column="section",
                rule_id="ATTENDEE_TABLE_COLUMNS",
                message=(
                    f'Attendee table must have 4 columns (found {table.num_cols}: '
                    "Name/Titles, Photo, Bio, Previously met)."
                ),
            )
        )
        return findings
    if table.num_rows < 2:
        findings.append(
            Finding(
                section_id="11_meeting_with",
                column="section",
                rule_id="ATTENDEE_TABLE_EMPTY",
                message="Attendee table has no attendees.",
            )
        )
        return findings
    for row_idx in range(1, table.num_rows):
        row = table.rows[row_idx]
        if not any(cell.strip() for cell in row):
            continue
        name_cell, _photo_cell, bio_cell, met_cell = row
        for label, pattern in _NAME_REQUIRED_FIELDS:
            if not pattern.search(name_cell):
                findings.append(
                    Finding(
                        section_id="11_meeting_with",
                        column="section",
                        rule_id=f"ATTENDEE_MISSING_{label.upper().replace(' ', '_')}",
                        message=f"Attendee row {row_idx}: missing {label}.",
                        evidence=name_cell.replace("\n", " | ")[:120],
                    )
                )
        if "\n" not in name_cell.strip() and " " in name_cell.strip():
            pass
        if not table.has_images:
            findings.append(
                Finding(
                    section_id="11_meeting_with",
                    column="section",
                    rule_id="ATTENDEE_PHOTO_MISSING",
                    message=f"Attendee row {row_idx}: professional headshot photo missing or unclear.",
                )
            )
        bio_lines = _count_lines(bio_cell)
        if bio_lines > 7:
            findings.append(
                Finding(
                    section_id="11_meeting_with",
                    column="section",
                    rule_id="ATTENDEE_BIO_TOO_LONG",
                    message=f"Attendee row {row_idx}: bio exceeds 7 lines (estimated {bio_lines}).",
                )
            )
        met_lines = _count_lines(met_cell)
        if met_lines > 7:
            findings.append(
                Finding(
                    section_id="11_meeting_with",
                    column="section",
                    rule_id="ATTENDEE_MET_TOO_LONG",
                    message=f"Attendee row {row_idx}: \"Previously met\" exceeds 7 lines.",
                )
            )
    return findings


_VERTEX_ATTENDEE_RE = re.compile(r"^[A-Z][\w'.\- ]+,\s*[A-Z][\w'.\- ,&]+$")
_NO_OTHER_RE = re.compile(r"^no other vertex attendees\.?$", re.IGNORECASE)


def check_vertex_attendees(brief: Brief) -> list[Finding]:
    section = brief.section("12_vertex_attendees")
    if section is None or not section.present:
        return []
    findings: list[Finding] = []
    text = section.raw_text.strip()
    if not text:
        findings.append(
            Finding(
                section_id="12_vertex_attendees",
                column="section",
                rule_id="VERTEX_ATTENDEE_MISSING",
                message='Section is empty. Must list attendees or state "No other Vertex attendees".',
            )
        )
        return findings
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    for line in lines:
        if _NO_OTHER_RE.match(line):
            continue
        if _VERTEX_ATTENDEE_RE.match(line):
            continue
        findings.append(
            Finding(
                section_id="12_vertex_attendees",
                column="section",
                rule_id="VERTEX_ATTENDEE_FORMAT",
                message=(
                    'Attendee line must follow format "[Name], [Title, Team Name]" '
                    'or state "No other Vertex attendees".'
                ),
                evidence=line,
            )
        )
    return findings


def _value_cell_text(section: Section) -> str:
    """For 2-col sections, return the text in the right-hand value cell."""
    if section.tables and section.tables[0].num_cols >= 2:
        return section.tables[0].rows[0][1]
    return section.raw_text


def _count_lines(text: str) -> int:
    if not text:
        return 0
    total = 0
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            total += 1
            continue
        wrapped = max(1, -(-len(line) // CHARS_PER_LINE))
        total += wrapped
    return total
