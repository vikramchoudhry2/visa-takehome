"""Structural / section-level deterministic checkers (rules B.2 - B.12).

Every check returns `Finding` objects with `column="section"`. Findings
about missing sections are produced by `check_section_presence`; the
other checkers each focus on one or two sections.

Line counts in Word are technically rendering-dependent. We approximate
"lines" as the count of soft-wrapped lines using a fixed character
budget per context plus explicit newlines. Full-width body sections use
``CHARS_PER_LINE`` (~95). The attendee Bio and "Previously met" cells sit
in narrow table columns, so they use ``ATTENDEE_TABLE_CELL_CHARS_PER_LINE``
(~50) so long unbroken paragraphs match Word wrap more closely.
Sections 9–10 often use the same label|value table column without Word list
markup; those bullets use ``LIST_BULLET_CHARS_PER_LINE`` for the 3-line cap
(~typical Word wrap width for a half-page value cell; tuned so one long
paragraph is not under-counted vs a full ``CHARS_PER_LINE`` body line).
"""

from __future__ import annotations

import re

from core.models import SECTION_TEMPLATE, Brief, Finding, Section

CHARS_PER_LINE = 95
# ~quarter-page column width at typical 11pt body — matches Word wrap in
# a 4-column attendee table far better than CHARS_PER_LINE alone.
ATTENDEE_TABLE_CELL_CHARS_PER_LINE = 50
LIST_BULLET_CHARS_PER_LINE = 102


def check_structure(brief: Brief) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(check_section_presence(brief))
    findings.extend(check_title(brief))
    findings.extend(check_two_column_tables(brief))
    findings.extend(check_one_line_sections(brief))
    findings.extend(check_two_line_sections(brief))
    findings.extend(check_key_facts_category_labels(brief))
    findings.extend(check_key_facts_lines(brief))
    findings.extend(check_exec_messages(brief))
    findings.extend(check_client_topics(brief))
    findings.extend(check_meeting_with(brief))
    findings.extend(check_vertex_attendees(brief))
    return findings


def check_section_presence(brief: Brief) -> list[Finding]:
    findings: list[Finding] = []
    for sid, display_title in SECTION_TEMPLATE:
        if sid == "08d_notable_changes":
            # Optional Key Facts subsection; never treated as a missing section.
            continue
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
                    message=f"{display} must not exceed 1 line.",
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
                    message=f"{display} must not exceed 2 lines.",
                    evidence=value_text[:200],
                )
            )
    return findings


_KEY_FACTS_LABEL_SPECS: tuple[tuple[str, str, str, str], ...] = (
    (r"\bbusiness\s+overview\b", "business overview", "Business Overview", "08a_business_overview"),
    (r"\bcompetition\b", "competition", "Competition", "08b_competition"),
    (r"\bvertex\s+overview\b", "vertex overview", "Vertex Overview", "08c_vertex_overview"),
)


def _kf_label_cell_head(left: str) -> str:
    head = left.strip().split(":", 1)[0]
    head = re.sub(r"^[\u2022•\-\*\s]+", "", head)
    head = re.sub(r"^only if applicable:\s*", "", head, flags=re.IGNORECASE).strip()
    head = re.sub(r"^\d{1,2}[a-d]\s*[\.\)]\s*", "", head, flags=re.IGNORECASE).strip()
    head = re.sub(r"\s*\(if applicable\)\s*$", "", head, flags=re.IGNORECASE).strip()
    return head.lower()


def _key_facts_label_visible(raw: str, tables: tuple, slug: str, pattern: str) -> bool:
    if re.search(pattern, raw, flags=re.IGNORECASE):
        return True
    for tbl in tables:
        if tbl.num_cols < 2:
            continue
        for row in tbl.rows:
            if len(row) < 2:
                continue
            if _kf_label_cell_head(row[0]) == slug:
                return True
    return False


def check_key_facts_category_labels(brief: Brief) -> list[Finding]:
    """B.8 — Key Facts umbrella heading is not a review row; labels map to 8A–8D rows."""
    anchor = brief.section("08a_business_overview")
    if anchor is None or not anchor.present:
        return []
    raw_for_labels = (brief.key_facts_combined_raw or "").strip()
    tables = anchor.tables
    if not raw_for_labels and not tables:
        return []
    findings: list[Finding] = []
    for pattern, slug, display, target_sid in _KEY_FACTS_LABEL_SPECS:
        if _key_facts_label_visible(raw_for_labels, tables, slug, pattern):
            continue
        findings.append(
            Finding(
                section_id=target_sid,
                column="section",
                rule_id="KEY_FACTS_CATEGORY_LABEL",
                message=(
                    f"Key Facts must clearly label {display} (missing or unclear "
                    "in the Key Facts block)."
                ),
            )
        )
    sec_8d = brief.section("08d_notable_changes")
    if (
        sec_8d is not None
        and sec_8d.present
        and sec_8d.raw_text.strip()
        and not _key_facts_label_visible(
            raw_for_labels,
            tables,
            "notable changes",
            r"\bnotable\s+changes\b",
        )
    ):
        findings.append(
            Finding(
                section_id="08d_notable_changes",
                column="section",
                rule_id="KEY_FACTS_CATEGORY_LABEL",
                message=(
                    "Key Facts must clearly label Notable Changes when that "
                    "subsection has content (missing or unclear label in the Key Facts block)."
                ),
            )
        )
    return findings


_KEY_FACT_LINE_CHECKS: tuple[tuple[str, str, int, str], ...] = (
    ("08a_business_overview", "Business Overview", 3, "KEY_FACTS_LINE_LIMIT"),
    ("08b_competition", "Competition", 3, "KEY_FACTS_LINE_LIMIT"),
    ("08c_vertex_overview", "Vertex Overview", 3, "KEY_FACTS_LINE_LIMIT"),
    ("08d_notable_changes", "Notable Changes", 2, "NOTABLE_CHANGES_LINE_LIMIT"),
)


def check_key_facts_lines(brief: Brief) -> list[Finding]:
    """Line-budget checks per Key Facts row (8A–8D); 8D body may be empty."""
    findings: list[Finding] = []
    for sid, display, max_lines, rule_id in _KEY_FACT_LINE_CHECKS:
        section = brief.section(sid)
        if section is None or not section.present:
            continue
        body = section.raw_text.strip()
        if not body:
            continue
        lines = _count_lines(body)
        if lines > max_lines:
            findings.append(
                Finding(
                    section_id=sid,
                    column="section",
                    rule_id=rule_id,
                    message=f'"{display}" must not exceed {max_lines} lines.',
                    evidence=body[:160],
                )
            )
    return findings


# --- Sections 9–10: executive messages & client topics ----------------------

_EXEC_MESSAGES_HEADER_LINE_RE = re.compile(
    r"^what\s+are\s+the\s+3\s*[-–]\s*5\s+messages.*(raise|president|executive)"
    r".*\??\s*$",
    re.IGNORECASE,
)
_CLIENT_TOPICS_HEADER_LINE_RE = re.compile(
    r"^any\s+issues\s+or\s+topics.*(raise|likely).*\??\s*$",
    re.IGNORECASE,
)


def _bullets_from_raw_plain_paragraphs(
    raw_text: str, header_line_re: re.Pattern[str]
) -> tuple[str, ...]:
    """One logical bullet per non-empty line when Word list bullets are absent."""
    lines = [ln.strip() for ln in raw_text.split("\n")]
    body: list[str] = []
    for ln in lines:
        if not ln:
            continue
        if not body and header_line_re.match(ln):
            continue
        body.append(ln)
    return tuple(body)


def _bullets_for_list_section(
    section: Section,
    header_line_re: re.Pattern[str],
) -> tuple[str, ...]:
    """Prefer Word list bullets; otherwise treat ``raw_text`` lines as bullets."""
    if section.bullets:
        return section.bullets
    return _bullets_from_raw_plain_paragraphs(section.raw_text, header_line_re)


def check_exec_messages(brief: Brief) -> list[Finding]:
    section = brief.section("09_exec_messages")
    if section is None or not section.present:
        return []
    findings: list[Finding] = []
    bullets = _bullets_for_list_section(section, _EXEC_MESSAGES_HEADER_LINE_RE)
    if len(bullets) > 5:
        findings.append(
            Finding(
                section_id="09_exec_messages",
                column="section",
                rule_id="MAX_FIVE_BULLETS",
                message=f"Exceeds 5 bullets (found {len(bullets)}).",
            )
        )
    if 0 < len(bullets) < 3:
        findings.append(
            Finding(
                section_id="09_exec_messages",
                column="section",
                rule_id="MIN_THREE_BULLETS",
                message=(
                    f"Template expects 3–5 messages (found {len(bullets)}); "
                    "add distinct talking points."
                ),
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
        lines = _count_lines(bullet, LIST_BULLET_CHARS_PER_LINE)
        if lines > 3:
            findings.append(
                Finding(
                    section_id="09_exec_messages",
                    column="section",
                    rule_id="BULLET_LINE_LIMIT",
                    message=f"Bullet {i} must not exceed 3 lines.",
                    evidence=bullet[:160],
                )
            )
    return findings


def check_client_topics(brief: Brief) -> list[Finding]:
    section = brief.section("10_client_topics")
    if section is None or not section.present:
        return []
    findings: list[Finding] = []
    bullets = _bullets_for_list_section(section, _CLIENT_TOPICS_HEADER_LINE_RE)
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
        lines = _count_lines(bullet, LIST_BULLET_CHARS_PER_LINE)
        if lines > 3:
            findings.append(
                Finding(
                    section_id="10_client_topics",
                    column="section",
                    rule_id="BULLET_LINE_LIMIT",
                    message=f"Bullet {i} must not exceed 3 lines.",
                    evidence=bullet[:160],
                )
            )
    return findings


# --- Section 11: "Who am I meeting with?" -----------------------------------
#
# Spec (from the take-home brief, restated):
#   The section must be a 4-column table with headers
#       Name/Titles | Photo | Bio | Previously met with Vertex exec?
#   The Name/Titles cell must include Name, Pronunciation, Title,
#   Preferred form of address, and Email.
#   The Photo cell must contain a professional headshot.
#   The Bio cell must be 1–2 sentences and at most 7 lines.
#   The "Previously met" cell must include who/when/where and be at most
#   7 lines.

# Expected header substrings, in column order. We compare case-insensitively
# and via substring so minor wording variations (e.g. "Previously met with
# Vertex exec" vs the canonical "Previously met with Vertex exec?") still
# match.
_ATTENDEE_EXPECTED_HEADERS: tuple[tuple[str, str], ...] = (
    ("Name/Titles", "name/titles"),
    ("Photo", "photo"),
    ("Bio", "bio"),
    ("Previously met with Vertex exec?", "previously met"),
)


# Title keywords cover C-suite, exec, finance, legal, ops, and common
# board roles. We treat any cell containing one of these as having a
# title. The list is intentionally broad to avoid false "missing Title"
# flags on real briefs.
_TITLE_KEYWORDS = (
    r"CEO|CFO|COO|CMO|CTO|CIO|CISO|CRO|CDO|CPO|CSO|CXO|"
    r"President|Vice\s+President|VP|SVP|EVP|AVP|"
    r"Director|Managing\s+Director|Manager|Head|Chief|Officer|"
    r"Lead|Partner|Principal|Founder|Co[-\s]?Founder|Owner|"
    r"Chair(?:man|woman|person)?|Treasurer|Controller|Counsel|"
    r"General\s+Manager|GM|Executive"
)
_ATTENDEE_TITLE_RE = re.compile(rf"\b(?:{_TITLE_KEYWORDS})\b", re.IGNORECASE)

# Pronunciation: parenthesized ALL-CAPS phonetic guide on the first line,
# e.g. "Jane Doe (JAYN DOH)".
_PRONUNCIATION_RE = re.compile(r"\([A-Z][A-Z' \-]*\)")

# Preferred form of address: either an explicit "Preferred:" / "Preferred
# name:" / "Preferred form:" label, or one of the common honorifics on a
# line by itself or followed by a name. Period-terminated honorifics
# already include their own boundary; for word-only ones we add a
# non-word lookahead so we don't match inside larger words.
_HONORIFICS = (
    r"Mr\.|Mrs\.|Ms\.|Mx\.|Dr\.|Prof\.|Rev\.|Hon\."
    r"|(?:Miss|Sir|Madam|Dame)(?=\W|$)"
)
_FORM_OF_ADDRESS_RE = re.compile(
    rf"(?:^|\n)\s*(?:Preferred(?:\s+\w+)?\s*:\s*\S+|(?:{_HONORIFICS}))",
    re.IGNORECASE | re.MULTILINE,
)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _attendee_name_first_line_ok(first_line: str) -> bool:
    """First line of Name/Titles must be `Name (PRONUNCIATION)` per template."""
    m = re.match(r"^(.+?)\s*\(([^)]+)\)\s*$", first_line.strip())
    if not m:
        return False
    name = m.group(1).strip()
    pron = m.group(2).strip()
    if len(name) < 2 or len(pron) < 1:
        return False
    return bool(re.search(r"[A-Za-z]", name))


def _extract_name_text(first_line: str) -> str:
    """Return the human name on the first line (ignoring pronunciation parens).

    Strips a trailing parenthesized pronunciation guide so a cell that
    contains *only* `(JAYN DOH)` is correctly detected as "no name".
    """
    stripped = first_line.strip()
    if not stripped:
        return ""
    candidate = re.sub(r"\s*\([^)]*\)\s*$", "", stripped).strip()
    if not candidate or not re.search(r"[A-Za-z]", candidate):
        return ""
    return candidate


def _check_attendee_headers(
    header_row: tuple[str, ...],
) -> list[str]:
    """Return display names of any expected header that is missing.

    Compares each header cell against the corresponding expected
    substring (case-insensitive). Returns canonical display names so
    error messages match the spec exactly.
    """
    missing: list[str] = []
    for idx, (display, needle) in enumerate(_ATTENDEE_EXPECTED_HEADERS):
        cell = header_row[idx].strip().lower() if idx < len(header_row) else ""
        if needle not in cell:
            missing.append(display)
    return missing


def _select_attendee_table(section: Section):
    """Return the table that looks most like the attendee 4-col table.

    Some real briefs wrap the entire body in an outer 2-column
    label|value table, which the parser surfaces as a synthetic 1x2
    `ParsedTable` for the section header. The real attendee table is
    then attached as a *nested* `ParsedTable` with 4 columns. We prefer
    a real 4-column table when one exists; otherwise we fall back to the
    first table so the column-count rule still reports the problem.
    """
    for table in section.tables:
        if table.num_cols == 4 and table.num_rows >= 1:
            return table
    return section.tables[0] if section.tables else None


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
                message=(
                    '"Who am I meeting with?" must be a 4-column table '
                    "(Name/Titles, Photo, Bio, Previously met with Vertex exec?)."
                ),
            )
        )
        return findings
    table = _select_attendee_table(section)
    if table is None:
        findings.append(
            Finding(
                section_id="11_meeting_with",
                column="section",
                rule_id="ATTENDEE_TABLE_MISSING",
                message=(
                    '"Who am I meeting with?" must be a 4-column table '
                    "(Name/Titles, Photo, Bio, Previously met with Vertex exec?)."
                ),
            )
        )
        return findings
    if table.num_cols != 4:
        findings.append(
            Finding(
                section_id="11_meeting_with",
                column="section",
                rule_id="ATTENDEE_TABLE_COLUMNS",
                message=(
                    f"Attendee table must have 4 columns (found {table.num_cols}): "
                    "Name/Titles, Photo, Bio, Previously met with Vertex exec?."
                ),
            )
        )
        return findings

    # Header row validation. Even with the correct column count the
    # headers themselves must match the template.
    header_row = table.rows[0] if table.num_rows >= 1 else ()
    missing_headers = _check_attendee_headers(header_row)
    if missing_headers:
        findings.append(
            Finding(
                section_id="11_meeting_with",
                column="section",
                rule_id="ATTENDEE_TABLE_HEADERS",
                message=(
                    "Attendee table headers must be "
                    '"Name/Titles | Photo | Bio | Previously met with Vertex exec?" '
                    f"(missing/incorrect: {', '.join(missing_headers)})."
                ),
                evidence=" | ".join(header_row)[:160] if header_row else None,
            )
        )

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
        name_cell, photo_cell, bio_cell, met_cell = row

        # ----- Name/Titles column ---------------------------------------
        first_line = name_cell.strip().split("\n")[0].strip() if name_cell.strip() else ""
        name_text = _extract_name_text(first_line)
        if not name_text:
            findings.append(
                Finding(
                    section_id="11_meeting_with",
                    column="section",
                    rule_id="ATTENDEE_MISSING_NAME",
                    message=f"Attendee row {row_idx}: missing Name.",
                    evidence=name_cell.replace("\n", " | ")[:120] or None,
                )
            )
        if first_line and not _attendee_name_first_line_ok(first_line):
            findings.append(
                Finding(
                    section_id="11_meeting_with",
                    column="section",
                    rule_id="ATTENDEE_NAME_LINE",
                    message=(
                        f"Attendee row {row_idx}: first line of Name/Titles must be "
                        "the attendee's name with pronunciation in parentheses "
                        "(e.g. 'Jane Doe (JAYN DOH)')."
                    ),
                    evidence=name_cell.replace("\n", " | ")[:120],
                )
            )
        # Each of these is a distinct spec field. Order matches the spec.
        per_field_checks: tuple[tuple[str, re.Pattern[str]], ...] = (
            ("Pronunciation", _PRONUNCIATION_RE),
            ("Title", _ATTENDEE_TITLE_RE),
            ("Preferred form of address", _FORM_OF_ADDRESS_RE),
            ("Email", _EMAIL_RE),
        )
        for label, pattern in per_field_checks:
            if not pattern.search(name_cell):
                findings.append(
                    Finding(
                        section_id="11_meeting_with",
                        column="section",
                        rule_id=f"ATTENDEE_MISSING_{label.upper().replace(' ', '_')}",
                        message=f"Attendee row {row_idx}: missing {label}.",
                        evidence=name_cell.replace("\n", " | ")[:120] or None,
                    )
                )

        # ----- Photo column ---------------------------------------------
        # Per spec, every attendee must have a professional headshot in
        # column 2. We check per-cell image presence (not just any image
        # in the table). A cell with no image but some text content
        # almost always means a placeholder like "(photo missing)" or a
        # caption stand-in, which we surface as a separate "unclear"
        # finding so reviewers can act on it.
        if not table.cell_has_image(row_idx, 1):
            findings.append(
                Finding(
                    section_id="11_meeting_with",
                    column="section",
                    rule_id="ATTENDEE_PHOTO_MISSING",
                    message=(
                        f"Attendee row {row_idx}: professional headshot missing "
                        "in Photo column."
                    ),
                    evidence=photo_cell.strip()[:120] or None,
                )
            )
        elif photo_cell.strip():
            # Image present and the cell also has text — most likely a
            # caption/placeholder beside the image, which often signals
            # an unclear or work-in-progress photo.
            findings.append(
                Finding(
                    section_id="11_meeting_with",
                    column="section",
                    rule_id="ATTENDEE_PHOTO_UNCLEAR",
                    message=(
                        f"Attendee row {row_idx}: Photo cell has text content "
                        "alongside the image; confirm the headshot is clear "
                        "and remove placeholder text."
                    ),
                    evidence=photo_cell.replace("\n", " | ")[:120],
                )
            )

        # ----- Bio column ------------------------------------------------
        bio_lines = _count_lines(bio_cell, ATTENDEE_TABLE_CELL_CHARS_PER_LINE)
        if bio_lines > 7:
            findings.append(
                Finding(
                    section_id="11_meeting_with",
                    column="section",
                    rule_id="ATTENDEE_BIO_TOO_LONG",
                    message=f"Attendee row {row_idx}: bio must not exceed 7 lines.",
                )
            )

        # ----- Previously met column ------------------------------------
        met_lines = _count_lines(met_cell, ATTENDEE_TABLE_CELL_CHARS_PER_LINE)
        if met_lines > 7:
            findings.append(
                Finding(
                    section_id="11_meeting_with",
                    column="section",
                    rule_id="ATTENDEE_MET_TOO_LONG",
                    message=f'Attendee row {row_idx}: "Previously met" must not exceed 7 lines.',
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
    # Use only the value cell of the section so the template label
    # ("Who is joining me from Vertex?") is not itself flagged as a
    # malformed attendee line. For sections without a synthetic table,
    # _value_cell_text falls back to raw_text (which is already
    # label-free because the header paragraph was consumed during parse).
    text = _value_cell_text(section).strip()
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


def _count_lines(text: str, chars_per_line: int | None = None) -> int:
    """Approximate visible line count (explicit newlines + soft wrap).

    ``chars_per_line`` defaults to :data:`CHARS_PER_LINE` for full-width
    body text. Narrow cells (e.g. attendee Bio) should pass a smaller
    budget so one long paragraph is not under-counted vs Word.
    """
    budget = chars_per_line if chars_per_line is not None else CHARS_PER_LINE
    if budget < 1:
        budget = CHARS_PER_LINE
    if not text:
        return 0
    total = 0
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            total += 1
            continue
        wrapped = max(1, -(-len(line) // budget))
        total += wrapped
    return total
