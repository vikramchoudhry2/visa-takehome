"""Deterministic formatting & grammar checkers.

Each checker is a pure function that takes a `Brief` and returns a list
of `Finding` objects with `column="formatting"`. They run regex / string
analysis on per-section text so we can attribute each finding to a
specific row in the output table.

Any global rule that fires inside a section is reported under that
section. Findings that fall outside any section default to the title
section so they still surface in the table.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from spellchecker import SpellChecker

from core.models import SECTION_TEMPLATE, Brief, Finding, Section

DEFAULT_FALLBACK_SECTION = "02_title"

_SECTION_ORDER = {sid: i for i, (sid, _) in enumerate(SECTION_TEMPLATE)}


_MONTHS_FULL = (
    "January",
    "February",
    "March",
    "April",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_MONTH_FULL_RE = re.compile(r"\b(" + "|".join(_MONTHS_FULL) + r")\b")
_MONTH_ANY_RE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b",
    re.IGNORECASE,
)

_DUPLICATE_WORDS_RE = re.compile(r"\b([A-Za-z]{2,})\s+\1\b", re.IGNORECASE)
_DUPLICATE_ALLOWLIST = {"that", "had", "is"}

_NUMBER_WORD_TO_DIGIT = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
    "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20",
}
_NUMBER_WORD_FRAG = "|".join(_NUMBER_WORD_TO_DIGIT.keys())
_DEAL_NOUN_FRAG = (
    r"(?:deal|partnership|agreement|contract|relationship|extension|renewal)"
)
# Catches "7 year deal", "seven year deal", "seven year strategic partnership",
# "seven-year agreement", etc. Allows up to 3 adjective words between the
# year-noun and the deal-noun so "seven year strategic partnership" matches.
_DEAL_BAD_RE = re.compile(
    r"\b(?P<num>\d+|" + _NUMBER_WORD_FRAG + r")[\s-]+"
    r"(?:year|years|yr|yrs)[\s-]+"
    r"(?:\w+\s+){0,3}?"
    + _DEAL_NOUN_FRAG + r"\b",
    re.IGNORECASE,
)
# Considered already-correct when written as "7-yr <deal-noun>"; the message
# also recommends that exact shape.
_DEAL_GOOD_RE = re.compile(
    r"\b\d+\s*-\s*yr(?:\s+\w+){0,3}?\s+" + _DEAL_NOUN_FRAG + r"\b",
    re.IGNORECASE,
)

_UNITED_STATES_RE = re.compile(r"\bUnited States\b")
_UNITED_STATES_ALLOWLIST = re.compile(
    r"\bUnited States (Postal|Treasury|Department|Government|Olympic|Senate|Congress|"
    r"Mint|Marine|Navy|Air Force|Army|Coast Guard|Supreme Court)\b"
)

_DOLLAR_BAD_RE = re.compile(
    r"\$\s*\d+(?:\.\d+)?\s*(?:million|mm|bn|billion|MM|BN)\b|\$\s*\d{1,3}(?:,\d{3}){2,}\b"
)
_DOLLAR_LONE_RE = re.compile(r"\$\s*\d+(?:\.\d+)?\b(?!\s*[MmBbKk])")

_DOUBLE_SPACE_AFTER_PERIOD_RE = re.compile(r"\.\s{2,}(?=[A-Z\"\(])")

_YEAR_TWO_DIGIT_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|"
    r"January|February|March|April|June|July|August|September|October|November|December)"
    r"\.?\s+(\d{2})\b(?!\d)",
    re.IGNORECASE,
)

_COMPETITORS = (
    ("Payments United", "PU"),
    ("NewPay", "NP"),
)

# Domain-specific terms the spellchecker should treat as known.
_SPELL_ALLOWLIST = frozenset(
    {
        "vertex",
        "acme",
        "fintech",
        "fintechs",
        "rfp",
        "rfps",
        "pv",
        "np",
        "pu",
        "newpay",
        "tokenization",
        "interchange",
        "issuer",
        "issuers",
        "issuing",
        "acquirer",
        "acquirers",
        "enablement",
        "enabler",
        "enablers",
        "enablement",
        "enablements",
        "merchant",
        "merchants",
        "cobrand",
        "yr",
        "ms",
        "mr",
        "mrs",
        "svp",
        "evp",
        "ceo",
        "cfo",
        "coo",
        "cmo",
        "cto",
        "h1",
        "h2",
        "q1",
        "q2",
        "q3",
        "q4",
        "ny",
        "nyc",
        "uk",
        "usd",
        "kpi",
        "kpis",
        "roi",
        "doh",
        "jayn",
        "jon",
        "smb",
        "smbs",
        "solutioning",
        "auth",
        "auths",
        "rebate",
        "rebates",
        "preauth",
        "ach",
        "wire",
        "btc",
        "etf",
        "etfs",
        "headshot",
        "roadmap",
        "roadmaps",
        "bio",
        "bios",
        "onboarding",
        "onboard",
        "offboarding",
        "upsell",
        "cross-sell",
        "crossell",
        "fintech",
        "ecommerce",
        "wallet",
        "wallets",
        "checkout",
        "issuance",
        "underwriting",
        "fx",
        "p2p",
        "b2b",
        "b2c",
        "kyc",
        "aml",
        "interchange",
        "rebates",
        "kpi",
        "kpis",
        "p&l",
        "ytd",
        "yoy",
        "qoq",
        "multi",
        "co",
        "th",
        "rd",
        "nd",
        "st",
        "mid",
        "non",
        "pre",
        "post",
        "sub",
        "ish",
    }
)

# Tokens are simple alphabetic runs. Hyphenated and slash-joined words
# are split before checking so each piece is validated independently.
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z']*")


def check_formatting(brief: Brief) -> list[Finding]:
    """Run formatting rules on the full document text and attribute hits
    to the narrowest containing section (per assessment: rules apply
    across the entire brief).

    Duplicate adjacent words are checked **per section** only, because the
    flattened `full_text` concatenates template labels with value cells
    (e.g. ``Meeting Objective`` next to ``Objective``) and would otherwise
    create false positives. Per-section findings already carry the right
    `section_id` and are NOT re-resolved during merge; only ghost-section
    findings (run against the full document) get attribution.
    """
    text = (brief.full_text or "").strip()
    if not text:
        return []
    ghost = Section(
        id=DEFAULT_FALLBACK_SECTION,
        title="",
        order=0,
        present=True,
        raw_text=text,
    )
    speller = _build_speller()
    chunks: list[list[Finding]] = []
    for s in brief.sections:
        if s.present and (s.raw_text or "").strip():
            chunks.append(_check_duplicate_words(s, s.raw_text))
    # Per-section checkers (already carry the right section_id).
    chunks.append(_check_double_space_per_section(brief))
    chunks.append(_check_competitor_abbreviations_per_section(brief))
    # Ghost (full-text) checkers; their section_id is the default fallback
    # and gets re-resolved below from the evidence text.
    chunks.extend(
        [
            _check_full_month(ghost, text),
            _check_two_digit_years(ghost, text),
            _check_deal_length(ghost, text),
            _check_united_states(ghost, text),
            _check_dollar_format(ghost, text),
            _check_spelling(ghost, text, speller),
        ]
    )
    merged: list[Finding] = []
    # Dedupe key includes section_id so the same violation may legitimately
    # appear in multiple sections (e.g., "Payments United" in both
    # Competition and Client Topics).
    seen: set[tuple[str, str, str, str]] = set()
    for group in chunks:
        for f in group:
            if f.section_id == DEFAULT_FALLBACK_SECTION:
                sid = _resolve_formatting_section_id(brief, f.evidence or f.message)
            else:
                sid = f.section_id
            nf = Finding(
                section_id=sid,
                column=f.column,
                rule_id=f.rule_id,
                message=f.message,
                evidence=f.evidence,
            )
            key = (nf.section_id, nf.rule_id, nf.message, nf.evidence or "")
            if key in seen:
                continue
            seen.add(key)
            merged.append(nf)
    return merged


_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_for_search(text: str) -> str:
    """Lower-case and collapse whitespace so substring search ignores
    newline/spacing and capitalization differences. The parser stores
    proper nouns with their original case ("Flenderson", "Vertx"), but
    spell-checker findings emit lower-cased evidence; without this the
    substring check would miss them and fall back to the title row.
    """
    return _WHITESPACE_RE.sub(" ", text).strip().lower()


def _resolve_formatting_section_id(brief: Brief, needle: str) -> str:
    """Pick the most specific section whose `raw_text` contains the
    evidence text (case-insensitive, whitespace-normalized).

    Prefer the shortest containing section (most specific). On a length
    tie, prefer the later template row (e.g. Key Facts child 08b over
    parent 08).
    """
    if not needle:
        return DEFAULT_FALLBACK_SECTION
    needle_norm = _normalize_for_search(needle)
    if not needle_norm:
        return DEFAULT_FALLBACK_SECTION
    candidates: list[tuple[int, str]] = []
    for s in brief.sections:
        if not s.present:
            continue
        raw_norm = _normalize_for_search(s.raw_text or "")
        if not raw_norm or needle_norm not in raw_norm:
            continue
        candidates.append((len(raw_norm), s.id))
    if not candidates:
        return DEFAULT_FALLBACK_SECTION
    return min(
        candidates,
        key=lambda c: (c[0], -_SECTION_ORDER.get(c[1], 0)),
    )[1]


def _build_speller() -> SpellChecker:
    sp = SpellChecker(distance=1)
    sp.word_frequency.load_words(_SPELL_ALLOWLIST)
    return sp


def _check_duplicate_words(section: Section, text: str) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[str] = set()
    for match in _DUPLICATE_WORDS_RE.finditer(text):
        word = match.group(1).lower()
        if word in _DUPLICATE_ALLOWLIST:
            continue
        snippet = _snippet(text, match.start(), match.end())
        if snippet in seen:
            continue
        seen.add(snippet)
        findings.append(
            Finding(
                section_id=section.id,
                column="formatting",
                rule_id="DUPLICATE_WORD",
                message=f'Duplicate word "{word}" - {snippet!r}',
                evidence=snippet,
            )
        )
    return findings


def _check_full_month(section: Section, text: str) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[str] = set()
    for match in _MONTH_FULL_RE.finditer(text):
        word = match.group(1)
        if word in seen:
            continue
        seen.add(word)
        findings.append(
            Finding(
                section_id=section.id,
                column="formatting",
                rule_id="MONTH_ABBREVIATION",
                message=f'Use 3-letter abbreviation for month - "{word}" should be "{word[:3]}"',
                evidence=word,
            )
        )
    return findings


def _check_two_digit_years(section: Section, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for match in _YEAR_TWO_DIGIT_RE.finditer(text):
        year = match.group(1)
        findings.append(
            Finding(
                section_id=section.id,
                column="formatting",
                rule_id="FULL_YEAR",
                message=f'Use full 4-digit year - "{year}" should be "20{year}"',
                evidence=match.group(0),
            )
        )
    return findings


def _check_deal_length(section: Section, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for match in _DEAL_BAD_RE.finditer(text):
        snippet = _snippet(text, match.start(), match.end())
        if _DEAL_GOOD_RE.search(snippet):
            continue
        raw_num = match.group("num").lower()
        digits = _NUMBER_WORD_TO_DIGIT.get(raw_num, raw_num)
        findings.append(
            Finding(
                section_id=section.id,
                column="formatting",
                rule_id="DEAL_LENGTH",
                message=(
                    f'Deal length must use "{digits}-yr" format '
                    f'(e.g., "{digits}-yr deal")'
                ),
                evidence=match.group(0),
            )
        )
    return findings


def _check_united_states(section: Section, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for match in _UNITED_STATES_RE.finditer(text):
        if _UNITED_STATES_ALLOWLIST.match(text, match.start()):
            continue
        findings.append(
            Finding(
                section_id=section.id,
                column="formatting",
                rule_id="ABBREVIATE_US",
                message='Abbreviate "United States" as "US"',
                evidence=match.group(0),
            )
        )
    return findings


def _check_dollar_format(section: Section, text: str) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[str] = set()
    for match in _DOLLAR_BAD_RE.finditer(text):
        token = match.group(0)
        if token in seen:
            continue
        seen.add(token)
        findings.append(
            Finding(
                section_id=section.id,
                column="formatting",
                rule_id="DOLLAR_FORMAT",
                message='Dollar amounts must use "$100M" abbreviation format',
                evidence=token,
            )
        )
    return findings


def _check_double_space_per_section(brief: Brief) -> list[Finding]:
    """Fire once per section that contains a double-space-after-period.

    Was previously a single global finding (broke after the first match),
    which meant only one section ever got flagged even when several had
    the problem.
    """
    findings: list[Finding] = []
    for s in brief.sections:
        if not s.present:
            continue
        body = s.raw_text or ""
        m = _DOUBLE_SPACE_AFTER_PERIOD_RE.search(body)
        if m is None:
            continue
        findings.append(
            Finding(
                section_id=s.id,
                column="formatting",
                rule_id="SINGLE_SPACE_AFTER_PERIOD",
                message="Use one space after a period (found multiple)",
                evidence=_snippet(body, m.start(), m.end()),
            )
        )
    return findings


_COMPETITOR_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = tuple(
    (re.compile(rf"\b{re.escape(name)}\b"), name, abbrev)
    for name, abbrev in _COMPETITORS
)


def _check_competitor_abbreviations_per_section(brief: Brief) -> list[Finding]:
    """Fire once per (section, competitor) so the same competitor is
    flagged in every section it appears (e.g. Competition AND Client
    Topics)."""
    findings: list[Finding] = []
    for s in brief.sections:
        if not s.present:
            continue
        body = s.raw_text or ""
        if not body:
            continue
        for pattern, full_name, abbrev in _COMPETITOR_PATTERNS:
            if not pattern.search(body):
                continue
            findings.append(
                Finding(
                    section_id=s.id,
                    column="formatting",
                    rule_id="COMPETITOR_ABBREVIATION",
                    message=f'Use abbreviation "{abbrev}" for "{full_name}"',
                    evidence=full_name,
                )
            )
    return findings


def _check_spelling(section: Section, text: str, speller: SpellChecker) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[str] = set()
    candidates: list[str] = []
    for token in _TOKEN_RE.findall(text):
        if any(c.isdigit() for c in token):
            continue
        if token != token.lower() and token != token.capitalize():
            continue
        if not token[0].isalpha():
            continue
        if token.lower() in _SPELL_ALLOWLIST:
            continue
        candidates.append(token.lower())
    if not candidates:
        return findings
    misspelled = speller.unknown(candidates)
    for word in misspelled:
        if word in seen:
            continue
        seen.add(word)
        if len(word) <= 2:
            continue
        suggestion = speller.correction(word)
        msg = f'Possible misspelling: "{word}"'
        if suggestion and suggestion != word:
            msg += f' (did you mean "{suggestion}"?)'
        findings.append(
            Finding(
                section_id=section.id,
                column="formatting",
                rule_id="SPELLING",
                message=msg,
                evidence=word,
            )
        )
    return findings


def _snippet(text: str, start: int, end: int, width: int = 30) -> str:
    s = max(0, start - width)
    e = min(len(text), end + width)
    return text[s:e].replace("\n", " ").strip()


def _flatten(items: Iterable[Iterable[Finding]]) -> list[Finding]:
    out: list[Finding] = []
    for sub in items:
        out.extend(sub)
    return out
