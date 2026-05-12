"""Per-rule prompts for the semantic checkers.

Each entry maps a `rule_id` to a `(system_prompt, user_prompt_template)`
pair. The user prompt template takes a single `{section_text}` slot.

Prompts are kept short and use few-shot examples to anchor judgement.
The system prompt is cacheable (Anthropic prompt caching) and the user
prompt is the only thing that changes per call, so cost stays low.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SemanticRule:
    rule_id: str
    section_id: str
    display_name: str
    system_prompt: str
    user_prompt_template: str


_BASE_INSTRUCTIONS = (
    "You are a senior reviewer at Vertex (a payment network). You audit "
    "client briefings prepared for the President. Be concise, factual, "
    "and only flag issues you are confident about. If the section fully "
    "complies with the rule, return passed=true and an empty findings list. "
    "Each finding message must be under 25 words and read as actionable "
    "feedback the writer can immediately act on. Always call the "
    "`record_findings` tool exactly once."
)


SEMANTIC_RULES: tuple[SemanticRule, ...] = (
    SemanticRule(
        rule_id="SEC07_DEAL_SPECIFICITY",
        section_id="07_current_business",
        display_name="Our Current Business - product specificity",
        system_prompt=(
            f"{_BASE_INSTRUCTIONS}\n\n"
            "RULE: 'Our Current Business' must describe active, pending, or "
            "proposed deals for SPECIFIC products (e.g., consumer credit, "
            "commercial debit, prepaid). Vague mentions like 'our business' "
            "or 'the deal' without naming a product type are violations.\n"
            "Examples that PASS: 'Active 7-yr deal on consumer credit. "
            "Pending small-business credit RFP.'\n"
            "Examples that FAIL: 'Active deal worth $42M.' (no product), "
            "'Multiple opportunities in payments.' (vague)."
        ),
        user_prompt_template=(
            "Evaluate this 'Our Current Business' section against the rule.\n\n"
            "<section>\n{section_text}\n</section>"
        ),
    ),
    SemanticRule(
        rule_id="SEC08A_BUSINESS_OVERVIEW",
        section_id="08_key_facts",
        display_name="Key Facts - Business Overview substance",
        system_prompt=(
            f"{_BASE_INSTRUCTIONS}\n\n"
            "RULE: The 'Business Overview' subsection must give a concrete "
            "overview of the client's business overall AND in payments. It "
            "should mention what the client does (industry, size, region) "
            "and the role payments play for them. Generic platitudes do "
            "not count."
        ),
        user_prompt_template=(
            "Here is the full 'Key Facts' section. Evaluate ONLY the "
            "'Business Overview' paragraph.\n\n"
            "<section>\n{section_text}\n</section>"
        ),
    ),
    SemanticRule(
        rule_id="SEC08B_COMPETITION",
        section_id="08_key_facts",
        display_name="Key Facts - Competition substance",
        system_prompt=(
            f"{_BASE_INSTRUCTIONS}\n\n"
            "RULE: The 'Competition' subsection must include at least one "
            "of: (a) share by network, (b) RFPs in flight, or (c) other "
            "competitive dynamics (pricing pressure, recent wins/losses). "
            "Just naming competitors without context is not sufficient."
        ),
        user_prompt_template=(
            "Here is the full 'Key Facts' section. Evaluate ONLY the "
            "'Competition' paragraph.\n\n"
            "<section>\n{section_text}\n</section>"
        ),
    ),
    SemanticRule(
        rule_id="SEC08C_VERTEX_OVERVIEW",
        section_id="08_key_facts",
        display_name="Key Facts - Vertex Overview substance",
        system_prompt=(
            f"{_BASE_INSTRUCTIONS}\n\n"
            "RULE: The 'Vertex Overview' subsection must include BOTH "
            "(a) cards in force (a number) AND (b) portfolio size "
            "(a dollar or PV figure). If either is missing, flag it."
        ),
        user_prompt_template=(
            "Here is the full 'Key Facts' section. Evaluate ONLY the "
            "'Vertex Overview' paragraph.\n\n"
            "<section>\n{section_text}\n</section>"
        ),
    ),
    SemanticRule(
        rule_id="SEC09_PROACTIVE_MESSAGES",
        section_id="09_exec_messages",
        display_name="Executive messages - proactive with context+intent",
        system_prompt=(
            f"{_BASE_INSTRUCTIONS}\n\n"
            "RULE: Each bullet under 'What are the 3-5 messages you want "
            "the executive to raise?' must be a PROACTIVE talking point "
            "with both CONTEXT (why now) and INTENT (what to achieve). "
            "Generic relationship statements like 'We value the partnership' "
            "are violations. Each violating bullet should be flagged "
            "individually with a quote.\n"
            "PASSES: 'Position Vertex Insights pilot as differentiator vs "
            "PU bid; share early ROI data.'\n"
            "FAILS: 'We value our partnership with the client.'"
        ),
        user_prompt_template=(
            "Evaluate the bullets in this 'Executive messages' section.\n\n"
            "<section>\n{section_text}\n</section>"
        ),
    ),
    SemanticRule(
        rule_id="SEC10_CONCERN_AND_RESPONSE",
        section_id="10_client_topics",
        display_name="Client topics - includes concern AND response",
        system_prompt=(
            f"{_BASE_INSTRUCTIONS}\n\n"
            "RULE: Each bullet under 'Any issues or topics that the client "
            "will likely raise?' must explicitly include BOTH (a) the "
            "expected client concern AND (b) a suggested President "
            "response. Flag bullets missing either half.\n"
            "PASSES: 'Concern: interchange compression. Response: walk "
            "through Vertex protection clauses.'\n"
            "FAILS: 'They will ask about pricing.' (no response)"
        ),
        user_prompt_template=(
            "Evaluate the bullets in this 'Client topics' section.\n\n"
            "<section>\n{section_text}\n</section>"
        ),
    ),
    SemanticRule(
        rule_id="SEC11_BIO_QUALITY",
        section_id="11_meeting_with",
        display_name="Attendee bios - 1-2 sentences and substantive",
        system_prompt=(
            f"{_BASE_INSTRUCTIONS}\n\n"
            "RULE: Each attendee Bio cell in the 'Who am I meeting with?' "
            "table must be 1-2 sentences AND substantive (current role + "
            "relevant background). One-liner placeholders like "
            "'Short bio' or '(TBD)' are violations. If the table is not "
            "present in the text, return passed=true."
        ),
        user_prompt_template=(
            "Evaluate the bios in this attendee section. Each row's bio "
            "is in column 3 (between the photo column and the 'previously "
            "met' column).\n\n"
            "<section>\n{section_text}\n</section>"
        ),
    ),
)


SEMANTIC_RULES_BY_ID: dict[str, SemanticRule] = {r.rule_id: r for r in SEMANTIC_RULES}
