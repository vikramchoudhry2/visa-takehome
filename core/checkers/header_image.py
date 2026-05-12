"""Section B.1 - Financial Institution icon must appear in the header."""

from __future__ import annotations

from core.models import Brief, Finding


def check_header_icon(brief: Brief) -> list[Finding]:
    if brief.header_images:
        return []
    return [
        Finding(
            section_id="01_header_icon",
            column="section",
            rule_id="HEADER_ICON_MISSING",
            message="Financial Institution icon is missing from the document header (top right).",
        )
    ]
