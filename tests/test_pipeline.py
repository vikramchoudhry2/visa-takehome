"""End-to-end pipeline + renderer tests."""

from __future__ import annotations

from core.llm.client import LLMFinding, LLMResult
from core.output.renderer import (
    COLUMN_HEADERS,
    NO_ISSUES,
    SECTION_MISSING,
    summary_counts,
    to_csv,
    to_dataframe,
    to_docx,
    to_markdown,
)
from core.pipeline import run_review
from tests.test_semantic import FakeClient


def test_pipeline_clean_brief_produces_no_findings(clean_bytes: bytes) -> None:
    outcome = run_review(clean_bytes, enable_semantic=False)
    assert summary_counts(outcome.report)["formatting"] == 0
    assert summary_counts(outcome.report)["section"] == 0
    assert summary_counts(outcome.report)["clean_sections"] == 12


def test_pipeline_dirty_brief_finds_issues(dirty_bytes: bytes) -> None:
    outcome = run_review(dirty_bytes, enable_semantic=False)
    counts = summary_counts(outcome.report)
    assert counts["formatting"] >= 9
    assert counts["section"] >= 5


def test_pipeline_with_mock_llm(dirty_bytes: bytes) -> None:
    fake = FakeClient(
        {
            "SEC09_PROACTIVE_MESSAGES": LLMResult(
                passed=False,
                findings=(LLMFinding(message="Bullet is generic"),),
            ),
        }
    )
    outcome = run_review(dirty_bytes, enable_semantic=True, llm_client=fake)
    assert outcome.semantic_enabled is True
    section9_findings = [
        f
        for sr in outcome.report.rows
        if sr.section_id == "09_exec_messages"
        for f in sr.section_findings
    ]
    assert any(f.rule_id == "SEC09_PROACTIVE_MESSAGES" for f in section9_findings)


def test_pipeline_without_api_key(monkeypatch, clean_bytes: bytes) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    outcome = run_review(clean_bytes, enable_semantic=True)
    assert outcome.semantic_enabled is False
    assert outcome.semantic_error is not None


def test_renderer_dataframe_has_expected_shape(clean_bytes: bytes) -> None:
    outcome = run_review(clean_bytes, enable_semantic=False)
    df = to_dataframe(outcome.report)
    assert list(df.columns) == list(COLUMN_HEADERS)
    assert len(df) == 12
    assert (df.iloc[:, 1] == NO_ISSUES).all()
    assert (df.iloc[:, 2] == NO_ISSUES).all()


def test_renderer_flags_missing_sections_in_table(monkeypatch) -> None:
    """Spec: 'If a section is missing, still include it and flag it as missing.'

    Either the explicit SECTION_MISSING placeholder OR a `SECTION_MISSING`
    finding text satisfies that requirement.
    """
    from io import BytesIO

    from docx import Document

    doc = Document()
    doc.add_paragraph("Stub Co Meeting Brief")
    buf = BytesIO()
    doc.save(buf)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    outcome = run_review(buf.getvalue(), enable_semantic=False)
    df = to_dataframe(outcome.report)
    section12 = df[df[COLUMN_HEADERS[0]] == "Who is joining me from Vertex?"].iloc[0]
    section_text = section12[COLUMN_HEADERS[2]]
    assert section_text != NO_ISSUES
    assert "missing" in section_text.lower()
    _ = SECTION_MISSING


def test_renderer_outputs_round_trip(clean_bytes: bytes) -> None:
    outcome = run_review(clean_bytes, enable_semantic=False)
    md = to_markdown(outcome.report)
    csv_bytes = to_csv(outcome.report)
    docx_bytes = to_docx(outcome.report)
    assert "Brief section" in md
    assert b"Brief section" in csv_bytes
    assert len(docx_bytes) > 1000
