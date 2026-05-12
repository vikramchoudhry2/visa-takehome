"""End-to-end review pipeline.

`run_review(brief_bytes)` is the single entrypoint the Streamlit app
calls. It returns the parsed `Brief` and the aggregated `ReviewReport`
so the UI can both display findings AND show the parsed structure for
transparency.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.checkers.formatting import check_formatting
from core.checkers.header_image import check_header_icon
from core.checkers.semantic import SupportsEvaluate, check_semantic
from core.checkers.structure import check_structure
from core.docx_parser import parse_brief
from core.llm.client import AnthropicClient, LLMUnavailable
from core.models import Brief, Finding, ReviewReport
from core.output.aggregator import aggregate


@dataclass(frozen=True)
class ReviewOutcome:
    brief: Brief
    report: ReviewReport
    semantic_enabled: bool
    semantic_error: str | None = None


def run_review(
    source: bytes,
    *,
    enable_semantic: bool = True,
    llm_client: SupportsEvaluate | None = None,
) -> ReviewOutcome:
    brief = parse_brief(source)
    findings: list[Finding] = []
    findings.extend(check_header_icon(brief))
    findings.extend(check_structure(brief))
    findings.extend(check_formatting(brief))

    semantic_enabled = False
    semantic_error: str | None = None
    if enable_semantic:
        client = llm_client
        if client is None:
            try:
                client = AnthropicClient()
            except LLMUnavailable as e:
                semantic_error = str(e)
        if client is not None:
            findings.extend(check_semantic(brief, client))
            semantic_enabled = True

    report = aggregate(brief, findings)
    return ReviewOutcome(
        brief=brief,
        report=report,
        semantic_enabled=semantic_enabled,
        semantic_error=semantic_error,
    )
