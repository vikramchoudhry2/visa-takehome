"""Semantic checker tests with a mocked LLM client."""

from __future__ import annotations

from core.checkers.semantic import check_semantic
from core.llm.client import LLMFinding, LLMResult
from core.llm.prompts import SEMANTIC_RULES
from core.models import Brief


class FakeClient:
    def __init__(self, responses: dict[str, LLMResult] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[str] = []

    def evaluate(self, *, rule_id: str, system_prompt: str, user_prompt: str) -> LLMResult:
        self.calls.append(rule_id)
        return self.responses.get(rule_id, LLMResult(passed=True, findings=()))


def test_semantic_calls_every_rule_for_present_sections(clean_brief: Brief) -> None:
    fake = FakeClient()
    check_semantic(clean_brief, fake)
    expected = {r.rule_id for r in SEMANTIC_RULES}
    assert set(fake.calls) == expected


def test_semantic_emits_findings_with_correct_section_id(dirty_brief: Brief) -> None:
    fake = FakeClient(
        {
            "SEC09_PROACTIVE_MESSAGES": LLMResult(
                passed=False,
                findings=(LLMFinding(message="Generic talking point", evidence="value our parntership"),),
            ),
        }
    )
    findings = check_semantic(dirty_brief, fake)
    assert len(findings) == 1
    f = findings[0]
    assert f.section_id == "09_exec_messages"
    assert f.column == "section"
    assert f.rule_id == "SEC09_PROACTIVE_MESSAGES"
    assert "Generic" in f.message


def test_semantic_skips_missing_sections() -> None:
    from io import BytesIO

    from docx import Document

    from core.docx_parser import parse_brief

    doc = Document()
    doc.add_paragraph("Stub Co Meeting Brief")
    buf = BytesIO()
    doc.save(buf)

    brief = parse_brief(buf.getvalue())
    fake = FakeClient()
    findings = check_semantic(brief, fake)
    assert findings == []
    assert fake.calls == []


def test_semantic_skips_vertex_substance_when_value_cell_empty() -> None:
    """Regression: empty Vertex value cell still yields non-empty `raw_text`
    (the template label). The LLM rule must not run or it duplicates
    `VERTEX_ATTENDEE_MISSING` with a second near-identical bullet."""
    from io import BytesIO

    from docx import Document

    from core.docx_parser import parse_brief

    doc = Document()
    doc.add_paragraph("Test Co Meeting Brief")
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Who is joining me from Vertex?"
    table.rows[0].cells[1].text = ""
    buf = BytesIO()
    doc.save(buf)
    brief = parse_brief(buf.getvalue())
    fake = FakeClient(
        {
            "SEC12_VERTEX_ATTENDEES_SUBSTANCE": LLMResult(
                passed=False,
                findings=(
                    LLMFinding(
                        message=(
                            'Section is empty. Must list Vertex attendees with name '
                            'and title/team or state "No other Vertex attendees".'
                        ),
                        evidence=None,
                    ),
                ),
            ),
        }
    )
    findings = check_semantic(brief, fake)
    assert "SEC12_VERTEX_ATTENDEES_SUBSTANCE" not in fake.calls
    assert findings == []


def test_semantic_no_client_returns_empty(monkeypatch, dirty_brief: Brief) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    findings = check_semantic(dirty_brief, client=None)
    assert findings == []
