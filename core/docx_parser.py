"""Parse a Vertex client briefing .docx into a `Brief` object.

Strategy:
1. Walk the document body in document order, interleaving paragraphs and
   tables (python-docx exposes them via the underlying XML element tree).
2. Identify section boundaries by fuzzy-matching paragraph text against
   the canonical template headers from `SECTION_TEMPLATE`.
3. Bucket subsequent paragraphs and tables into the active section until
   the next header is found.
4. Special-case section 01 (header icon) and section 02 (title) — these
   live in the header / first paragraph respectively, not as their own
   labeled body sections.
5. Always emit all 12 sections in template order; sections we couldn't
   find are emitted with `present=False`.

Fuzzy matching uses rapidfuzz with a conservative score threshold so
small wording deltas (e.g., en-dash vs hyphen, smart quotes) don't break
section detection.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterator
from dataclasses import dataclass

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph
from rapidfuzz import fuzz

from core.models import (
    SECTION_TEMPLATE,
    Brief,
    ImageRef,
    ParsedTable,
    Section,
)

FUZZY_HEADER_THRESHOLD = 82

BODY_HEADER_IDS_IN_ORDER: tuple[str, ...] = (
    "03_client_name_type",
    "04_meeting_objective",
    "05_client_markets",
    "06_client_share",
    "07_current_business",
    "08_key_facts",
    "09_exec_messages",
    "10_client_topics",
    "11_meeting_with",
    "12_vertex_attendees",
)


@dataclass
class _Block:
    """A paragraph or table from the body, in document order."""

    kind: str
    paragraph: Paragraph | None = None
    table: Table | None = None


def parse_brief(source: bytes | io.BytesIO | str) -> Brief:
    """Parse a docx file (path, bytes, or stream) into a `Brief`."""
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    doc = Document(source)
    return _parse_document(doc)


def _parse_document(doc: DocxDocument) -> Brief:
    blocks = list(_iter_body_blocks(doc))
    header_images = _extract_header_images(doc)
    title_text, title_idx = _extract_title(blocks)
    full_text = _collect_full_text(blocks, doc)

    body_section_blocks = _split_body_into_sections(
        blocks, start_idx=title_idx + 1 if title_idx is not None else 0
    )

    sections: list[Section] = []
    for order, (sid, display_title) in enumerate(SECTION_TEMPLATE, start=1):
        if sid == "01_header_icon":
            sections.append(
                Section(
                    id=sid,
                    title=display_title,
                    order=order,
                    present=bool(header_images),
                    images=tuple(header_images),
                )
            )
        elif sid == "02_title":
            sections.append(
                Section(
                    id=sid,
                    title=display_title,
                    order=order,
                    present=title_text is not None,
                    raw_text=title_text or "",
                )
            )
        else:
            blocks_for_section = body_section_blocks.get(sid)
            if not blocks_for_section:
                sections.append(
                    Section(id=sid, title=display_title, order=order, present=False)
                )
            else:
                sections.append(
                    _section_from_blocks(sid, display_title, order, blocks_for_section)
                )

    client_name = _infer_client_name(title_text)

    return Brief(
        client_name=client_name,
        title_text=title_text,
        header_images=tuple(header_images),
        sections=tuple(sections),
        full_text=full_text,
    )


def _iter_body_blocks(doc: DocxDocument) -> Iterator[_Block]:
    """Yield paragraphs and tables in document order."""
    body = doc.element.body
    for child in body.iterchildren():
        tag = child.tag
        if tag == qn("w:p"):
            yield _Block(kind="paragraph", paragraph=Paragraph(child, doc))
        elif tag == qn("w:tbl"):
            yield _Block(kind="table", table=Table(child, doc))


def _extract_header_images(doc: DocxDocument) -> list[ImageRef]:
    images: list[ImageRef] = []
    for sect in doc.sections:
        for header in (sect.header, sect.first_page_header, sect.even_page_header):
            if header is None:
                continue
            for shape in _iter_inline_shapes(header._element):
                images.append(
                    ImageRef(
                        location="header",
                        width_emu=shape.get("cx"),
                        height_emu=shape.get("cy"),
                    )
                )
    return images


def _iter_inline_shapes(element) -> Iterator[dict]:
    """Yield {cx, cy} dicts for every embedded image under `element`."""
    for blip in element.iter(qn("a:blip")):
        extent = None
        for parent in blip.iterancestors():
            extent = parent.find(qn("wp:extent"))
            if extent is not None:
                break
        cx = int(extent.get("cx")) if extent is not None and extent.get("cx") else None
        cy = int(extent.get("cy")) if extent is not None and extent.get("cy") else None
        yield {"cx": cx, "cy": cy}


def _has_inline_image(element) -> bool:
    return next(iter(element.iter(qn("a:blip"))), None) is not None


def _extract_title(blocks: list[_Block]) -> tuple[str | None, int | None]:
    """Find the brief title. By spec, must be `[Client Name] Meeting Brief`.

    Search the first ~10 non-empty paragraphs for one containing
    'Meeting Brief'.
    """
    seen = 0
    for idx, block in enumerate(blocks):
        if block.kind != "paragraph":
            continue
        text = block.paragraph.text.strip()
        if not text:
            continue
        seen += 1
        if "meeting brief" in text.lower():
            return text, idx
        if seen >= 10:
            break
    return None, None


def _collect_full_text(blocks: list[_Block], doc: DocxDocument) -> str:
    parts: list[str] = []
    for block in blocks:
        if block.kind == "paragraph":
            txt = block.paragraph.text
            if txt:
                parts.append(txt)
        else:
            for row in block.table.rows:
                for cell in row.cells:
                    cell_text = "\n".join(p.text for p in cell.paragraphs if p.text)
                    if cell_text:
                        parts.append(cell_text)
    return "\n".join(parts)


def _split_body_into_sections(
    blocks: list[_Block], start_idx: int
) -> dict[str, list[_Block]]:
    """Walk body blocks, splitting them into per-section block lists."""
    section_buckets: dict[str, list[_Block]] = {}
    current_id: str | None = None

    for block in blocks[start_idx:]:
        matched_id = _match_block_to_header(block)
        if matched_id is not None and matched_id != current_id:
            current_id = matched_id
            section_buckets.setdefault(current_id, [])
            continue
        if current_id is None:
            continue
        section_buckets.setdefault(current_id, []).append(block)

    return section_buckets


def _match_block_to_header(block: _Block) -> str | None:
    """Return the section id this block is a header for, or None.

    Matches if the block is a paragraph whose text closely resembles a
    template header. Tables are never headers. Header text may also
    appear inside the first cell of a 2-col table for sections 3-7; we
    don't treat those as header markers because they're already inside
    the section body.
    """
    if block.kind != "paragraph":
        return None
    text = block.paragraph.text.strip()
    if not text:
        return None
    normalized = _normalize(text)
    best_id: str | None = None
    best_score = 0
    for sid, display_title in SECTION_TEMPLATE:
        if sid not in BODY_HEADER_IDS_IN_ORDER:
            continue
        target = _normalize(display_title)
        score = fuzz.ratio(normalized, target)
        if score > best_score:
            best_score = score
            best_id = sid
    if best_score >= FUZZY_HEADER_THRESHOLD:
        return best_id
    return None


_NORMALIZE_RE = re.compile(r"[\s\u2010-\u2015\-]+")


def _normalize(text: str) -> str:
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = _NORMALIZE_RE.sub(" ", text)
    return text.strip().lower()


def _section_from_blocks(
    section_id: str, title: str, order: int, blocks: list[_Block]
) -> Section:
    text_parts: list[str] = []
    bullets: list[str] = []
    tables: list[ParsedTable] = []
    images: list[ImageRef] = []

    for block in blocks:
        if block.kind == "paragraph":
            p = block.paragraph
            txt = p.text
            if txt.strip():
                text_parts.append(txt)
                if _is_list_paragraph(p):
                    bullets.append(txt.strip())
            for _shape in _iter_inline_shapes(p._element):
                images.append(ImageRef(location="body"))
        else:
            tbl = block.table
            tables.append(_parse_table(tbl))
            for cell in _iter_table_cells(tbl):
                cell_text = "\n".join(par.text for par in cell.paragraphs if par.text)
                if cell_text.strip():
                    text_parts.append(cell_text)
                for par in cell.paragraphs:
                    if _is_list_paragraph(par) and par.text.strip():
                        bullets.append(par.text.strip())
                    if _has_inline_image(par._element):
                        images.append(ImageRef(location="table_cell"))

    return Section(
        id=section_id,
        title=title,
        order=order,
        present=True,
        raw_text="\n".join(text_parts),
        bullets=tuple(bullets),
        tables=tuple(tables),
        images=tuple(images),
    )


def _iter_table_cells(table: Table) -> Iterator[_Cell]:
    seen: set[int] = set()
    for row in table.rows:
        for cell in row.cells:
            cid = id(cell._tc)
            if cid in seen:
                continue
            seen.add(cid)
            yield cell


def _parse_table(table: Table) -> ParsedTable:
    rows: list[tuple[str, ...]] = []
    has_images = False
    for row in table.rows:
        cells: list[str] = []
        for cell in row.cells:
            cell_text = "\n".join(p.text for p in cell.paragraphs)
            cells.append(cell_text)
            if not has_images:
                for par in cell.paragraphs:
                    if _has_inline_image(par._element):
                        has_images = True
                        break
        rows.append(tuple(cells))
    return ParsedTable(rows=tuple(rows), has_images=has_images)


def _is_list_paragraph(paragraph: Paragraph) -> bool:
    """A paragraph is a list/bullet if it has a numPr element OR a list-style style.

    Word stores list membership in two places: a `<w:numPr>` element on
    the paragraph (or inherited from its style), or via a style whose
    name begins with `List`. We treat either as a bullet.
    """
    pPr = paragraph._p.find(qn("w:pPr"))
    if pPr is not None and pPr.find(qn("w:numPr")) is not None:
        return True
    style = paragraph.style
    if style is None or style.name is None:
        return False
    name = style.name.lower()
    return name.startswith("list ") or name == "list bullet" or name == "list number"


def _infer_client_name(title_text: str | None) -> str | None:
    if not title_text:
        return None
    match = re.match(r"^(.*?)\s+Meeting Brief\b", title_text.strip(), re.IGNORECASE)
    if not match:
        return None
    name = match.group(1).strip().strip("[]")
    return name or None


