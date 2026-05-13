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

from core.checkers.structure import _value_cell_text
from core.llm.client import AnthropicClient, LLMResult, LLMUnavailable
from core.llm.prompts import SEMANTIC_RULES, SemanticRule
from core.models import Brief, Finding


class SupportsEvaluate(Protocol):
    def evaluate(
        self,
        *,
        rule_id: str,
        system_prompt: str,
        user_prompt: str,
    ) -> LLMResult: ...


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
        if section is None or not section.present or not section.raw_text.strip():
            continue
        # Section 12: `raw_text` includes the template label even when the
        # value cell is empty, so `raw_text.strip()` is non-empty while the
        # substantive body is blank. Deterministic `VERTEX_ATTENDEE_MISSING`
        # already covers that; skip the LLM rule to avoid duplicate bullets.
        if rule.section_id == "12_vertex_attendees" and not _value_cell_text(
            section
        ).strip():
            continue
        result = _evaluate_rule(client, rule, section.raw_text)
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
