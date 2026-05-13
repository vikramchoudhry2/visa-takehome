"""Semantic (LLM-backed) checkers for substance/judgment rows: 3–7, Key Facts
(8A–8D where applicable), 9–12, plus client markets (5) and Vertex attendees (12).

The semantic checker accepts an `AnthropicClient` (or anything with the
same `.evaluate(...)` shape, which makes mocking trivial in tests).

If no client is supplied or `LLMUnavailable` is raised at construction
time, semantic checks are skipped silently and the deterministic
findings stand on their own. The Streamlit UI surfaces this state.
"""

from __future__ import annotations

from typing import Protocol

from core.checkers.structure import (
    _select_attendee_table,
    _value_cell_text,
    check_vertex_attendees,
)
from core.llm.client import AnthropicClient, LLMResult, LLMUnavailable
from core.llm.prompts import SEMANTIC_RULES, SemanticRule
from core.models import Brief, Finding, Section


class SupportsEvaluate(Protocol):
    def evaluate(
        self,
        *,
        rule_id: str,
        system_prompt: str,
        user_prompt: str,
    ) -> LLMResult: ...


def _format_meeting_attendee_table_for_semantic(section: Section) -> str:
    """Column-labeled attendee rows for LLM prompts.

    `Section.raw_text` concatenates table cells without headers, so models
    often mis-attribute Bio vs ``Previously met`` when the last column is
    empty or short. Structure checks use ``ParsedTable`` column indices;
    semantic rules should see the same alignment.
    """
    table = _select_attendee_table(section)
    if table is None or table.num_cols != 4 or table.num_rows < 2:
        return ""
    lines: list[str] = [
        "Attendee grid (column-aligned extract). Use **Bio** only for bio "
        "quality; use **Previously met with Vertex exec?** only for that rule.",
        f"Header row: {' | '.join(c.strip().replace(chr(10), ' ') for c in table.rows[0])}",
    ]
    for row_idx in range(1, table.num_rows):
        row = table.rows[row_idx]
        if not any(cell.strip() for cell in row):
            continue
        if len(row) < 4:
            continue
        name_cell, photo_cell, bio_cell, met_cell = row
        lines.append("")
        lines.append(f"--- Attendee row {row_idx} ---")
        lines.append(f"Name/Titles:\n{name_cell.strip() or '(empty)'}")
        lines.append(f"Photo cell text:\n{photo_cell.strip() or '(empty)'}")
        lines.append(f"Bio:\n{bio_cell.strip() or '(empty)'}")
        lines.append(
            "Previously met with Vertex exec?:\n"
            f"{met_cell.strip() or '(empty)'}"
        )
    return "\n".join(lines).strip()


def _section_text_for_semantic(section: Section, rule: SemanticRule) -> str:
    """Text passed into ``{section_text}`` for one semantic rule."""
    if rule.section_id == "11_meeting_with":
        structured = _format_meeting_attendee_table_for_semantic(section)
        if structured:
            return structured
    return section.raw_text


def check_semantic(
    brief: Brief, client: SupportsEvaluate | None = None
) -> list[Finding]:
    """Run all semantic rules. Returns an empty list if no client and no
    `ANTHROPIC_API_KEY` is configured."""
    if client is None:
        try:
            client = AnthropicClient()
        except LLMUnavailable:
            return []

    findings: list[Finding] = []
    for rule in SEMANTIC_RULES:
        section = brief.section(rule.section_id)
        if section is None or not section.present:
            continue
        section_text = _section_text_for_semantic(section, rule)
        if not section_text.strip():
            continue
        # Section 12: skip LLM when deterministic Vertex attendee checks
        # already cover the issue (empty value or line-format regex), so the
        # model does not echo the same advice as VERTEX_ATTENDEE_MISSING /
        # VERTEX_ATTENDEE_FORMAT.
        if rule.section_id == "12_vertex_attendees":
            if not _value_cell_text(section).strip():
                continue
            if rule.rule_id == "SEC12_VERTEX_ATTENDEES_SUBSTANCE" and any(
                f.rule_id == "VERTEX_ATTENDEE_FORMAT"
                for f in check_vertex_attendees(brief)
            ):
                continue
        result = _evaluate_rule(client, rule, section_text)
        if result.passed and not result.findings:
            continue
        for f in result.findings:
            findings.append(
                Finding(
                    section_id=rule.section_id,
                    column="section",
                    rule_id=rule.rule_id,
                    message=f.message,
                    evidence=f.evidence,
                )
            )
    return findings


def _evaluate_rule(
    client: SupportsEvaluate, rule: SemanticRule, section_text: str
) -> LLMResult:
    user_prompt = rule.user_prompt_template.format(section_text=section_text)
    return client.evaluate(
        rule_id=rule.rule_id,
        system_prompt=rule.system_prompt,
        user_prompt=user_prompt,
    )
