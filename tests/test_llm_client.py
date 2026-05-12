"""Tests for AnthropicClient pure helpers (no network calls)."""

from __future__ import annotations

import pytest

from core.llm.client import (
    AnthropicClient,
    LLMFinding,
    LLMResult,
    LLMUnavailable,
    _parse_tool_input,
)


def test_no_api_key_raises_unavailable(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMUnavailable):
        AnthropicClient(api_key=None)


def test_parse_tool_input_with_findings() -> None:
    res = _parse_tool_input(
        {
            "passed": False,
            "findings": [
                {"message": "Bad bullet", "evidence": "value our partnership"},
                {"message": "Generic"},
            ],
        }
    )
    assert res.passed is False
    assert len(res.findings) == 2
    assert res.findings[0].evidence == "value our partnership"
    assert res.findings[1].evidence is None


def test_parse_tool_input_passed_with_empty() -> None:
    res = _parse_tool_input({"passed": True, "findings": []})
    assert res.passed is True
    assert res.findings == ()


def test_parse_tool_input_string_payload() -> None:
    res = _parse_tool_input('{"passed": true, "findings": []}')
    assert res.passed is True


def test_parse_tool_input_malformed_json() -> None:
    res = _parse_tool_input("{not json")
    assert res.passed is False
    assert "malformed" in res.findings[0].message.lower()


def test_parse_tool_input_unexpected_type() -> None:
    res = _parse_tool_input(["not", "a", "dict"])
    assert res.passed is False


def test_cache_key_is_deterministic_and_distinct() -> None:
    a = AnthropicClient._cache_key("R1", "sys", "user1")
    b = AnthropicClient._cache_key("R1", "sys", "user1")
    c = AnthropicClient._cache_key("R1", "sys", "user2")
    d = AnthropicClient._cache_key("R2", "sys", "user1")
    assert a == b
    assert a != c
    assert a != d


def test_call_with_retry_returns_failure_on_persistent_error(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = AnthropicClient()

    class BoomError(Exception):
        pass

    def boom(*args, **kwargs):
        raise BoomError("nope")

    monkeypatch.setattr(client, "_call_once", boom)
    res = client._call_with_retry("sys", "user", max_retries=1)
    assert res.passed is False
    assert "BoomError" in res.findings[0].message


def test_evaluate_uses_cache(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = AnthropicClient()
    calls: list[int] = []

    def fake_once(system_prompt: str, user_prompt: str) -> LLMResult:
        calls.append(1)
        return LLMResult(passed=True, findings=())

    monkeypatch.setattr(client, "_call_once", fake_once)
    client.evaluate(rule_id="R", system_prompt="sys", user_prompt="user")
    client.evaluate(rule_id="R", system_prompt="sys", user_prompt="user")
    assert len(calls) == 1


def test_transient_error_classification(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    class RateLimitError(Exception):
        pass

    class ValueError2(Exception):
        pass

    assert AnthropicClient._is_transient(RateLimitError("rate")) is True
    assert AnthropicClient._is_transient(ValueError2("x")) is False


def test_llm_finding_immutable() -> None:
    f = LLMFinding(message="x")
    with pytest.raises(Exception):
        f.message = "y"
