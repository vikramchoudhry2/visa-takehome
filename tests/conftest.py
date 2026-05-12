"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from core.docx_parser import parse_brief
from core.models import Brief
from tests.fixtures.builder import build_clean_brief, build_dirty_brief


@pytest.fixture(scope="session")
def clean_bytes() -> bytes:
    return build_clean_brief()


@pytest.fixture(scope="session")
def dirty_bytes() -> bytes:
    return build_dirty_brief()


@pytest.fixture(scope="session")
def clean_brief(clean_bytes: bytes) -> Brief:
    return parse_brief(clean_bytes)


@pytest.fixture(scope="session")
def dirty_brief(dirty_bytes: bytes) -> Brief:
    return parse_brief(dirty_bytes)
