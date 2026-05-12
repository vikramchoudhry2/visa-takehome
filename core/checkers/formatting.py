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

from core.models import Brief, Finding, Section

DEFAULT_FALLBACK_SECTION = "02_title"


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

_DEAL_BAD_RE = re.compile(r"\b(\d+)\s*[- ]?\s*(year|years|yrs)\s+deal\b", re.IGNORECASE)
_DEAL_GOOD_RE = re.compile(r"\b\d+\s*-\s*yr\s+deal\b", re.IGNORECASE)

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
        "enabler",
        "enablers",
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
    """Run every formatting/grammar rule and return all findings."""
    findings: list[Finding] = []
    speller = _build_speller()
    for section in brief.sections:
        if not section.present or not section.raw_text:
            continue
        text = section.raw_text
        findings.extend(_check_duplicate_words(section, text))
        findings.extend(_check_full_month(section, text))
        findings.extend(_check_two_digit_years(section, text))
        findings.extend(_check_deal_length(section, text))
        findings.extend(_check_united_states(section, text))
        findings.extend(_check_dollar_format(section, text))
        findings.extend(_check_double_space(section, text))
        findings.extend(_check_competitor_abbreviations(section, text, brief))
        findings.extend(_check_spelling(section, text, speller))
    return findings


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
                evidence=_snippet(text, match.start(), match.end()),
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
                evidence=_snippet(text, match.start(), match.end()),
            )
        )
    return findings


def _check_deal_length(section: Section, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for match in _DEAL_BAD_RE.finditer(text):
        snippet = _snippet(text, match.start(), match.end())
        if _DEAL_GOOD_RE.search(snippet):
            continue
        years = match.group(1)
        findings.append(
            Finding(
                section_id=section.id,
                column="formatting",
                rule_id="DEAL_LENGTH",
                message=f'Deal length must use "{years}-yr deal" format',
                evidence=snippet,
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
                evidence=_snippet(text, match.start(), match.end()),
            )
        )
    return findings


def _check_dollar_format(section: Section, text: str) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[str] = set()
    for match in _DOLLAR_BAD_RE.finditer(text):
        snippet = _snippet(text, match.start(), match.end())
        if snippet in seen:
            continue
        seen.add(snippet)
        findings.append(
            Finding(
                section_id=section.id,
                column="formatting",
                rule_id="DOLLAR_FORMAT",
                message='Dollar amounts must use "$100M" abbreviation format',
                evidence=snippet,
            )
        )
    return findings


def _check_double_space(section: Section, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for match in _DOUBLE_SPACE_AFTER_PERIOD_RE.finditer(text):
        findings.append(
            Finding(
                section_id=section.id,
                column="formatting",
                rule_id="SINGLE_SPACE_AFTER_PERIOD",
                message="Use one space after a period (found multiple)",
                evidence=_snippet(text, match.start(), match.end()),
            )
        )
        break
    return findings


def _check_competitor_abbreviations(
    section: Section, text: str, brief: Brief
) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for full_name, abbrev in _COMPETITORS:
        pattern = re.compile(rf"\b{re.escape(full_name)}\b")
        for match in pattern.finditer(text):
            key = (full_name, _snippet(text, match.start(), match.end()))
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                Finding(
                    section_id=section.id,
                    column="formatting",
                    rule_id="COMPETITOR_ABBREVIATION",
                    message=f'Use abbreviation "{abbrev}" for "{full_name}"',
                    evidence=_snippet(text, match.start(), match.end()),
                )
            )
    _ = brief
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
