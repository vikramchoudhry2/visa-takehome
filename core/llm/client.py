"""Thin Anthropic Claude wrapper for semantic checks.

Design:
- One client instance per request, stateless.
- Forces a single tool definition `record_findings` so Claude must
  return structured JSON we can validate.
- Retries on transient API errors with exponential backoff.
- Optional in-process LRU cache keyed on (rule_id, section_text) so
  re-running the same brief in the UI doesn't pay for the same calls.
- Defaults to Claude 3.5 Sonnet (latest stable). Can be overridden via
  `ANTHROPIC_MODEL` env var.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_MODEL = "claude-sonnet-4-5"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.0

RECORD_FINDINGS_TOOL = {
    "name": "record_findings",
    "description": (
        "Record the result of a single semantic compliance check. "
        "If the section fully complies, return an empty findings list."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "passed": {
                "type": "boolean",
                "description": "True if the section fully complies with the rule.",
            },
            "findings": {
                "type": "array",
                "description": "One entry per distinct violation. Empty if passed.",
                "items": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Concise (<25 words) feedback bullet for the reviewer.",
                        },
                        "evidence": {
                            "type": "string",
                            "description": "Short quote from the section that triggered the finding.",
                        },
                    },
                    "required": ["message"],
                },
            },
        },
        "required": ["passed", "findings"],
    },
}


@dataclass(frozen=True)
class LLMFinding:
    message: str
    evidence: str | None = None


@dataclass(frozen=True)
class LLMResult:
    passed: bool
    findings: tuple[LLMFinding, ...]


class LLMUnavailable(Exception):
    """Raised when the Anthropic client cannot be constructed (no key)."""


class AnthropicClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
    ):
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise LLMUnavailable("anthropic SDK not installed") from e
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMUnavailable(
                "ANTHROPIC_API_KEY is not set. Add it to your environment "
                "or to .streamlit/secrets.toml to enable semantic checks."
            )
        self._client = Anthropic(api_key=key)
        self._model = model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._cache: dict[str, LLMResult] = {}

    def evaluate(
        self,
        *,
        rule_id: str,
        system_prompt: str,
        user_prompt: str,
        max_retries: int = 3,
    ) -> LLMResult:
        cache_key = self._cache_key(rule_id, system_prompt, user_prompt)
        if cache_key in self._cache:
            return self._cache[cache_key]
        result = self._call_with_retry(system_prompt, user_prompt, max_retries)
        self._cache[cache_key] = result
        return result

    def _call_with_retry(
        self, system_prompt: str, user_prompt: str, max_retries: int
    ) -> LLMResult:
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                return self._call_once(system_prompt, user_prompt)
            except Exception as e:
                last_exc = e
                if not self._is_transient(e) or attempt == max_retries - 1:
                    break
                time.sleep(2**attempt)
        return LLMResult(
            passed=False,
            findings=(
                LLMFinding(
                    message=f"LLM check failed after retries: {type(last_exc).__name__}",
                ),
            ),
        )

    def _call_once(self, system_prompt: str, user_prompt: str) -> LLMResult:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[RECORD_FINDINGS_TOOL],
            tool_choice={"type": "tool", "name": "record_findings"},
            messages=[{"role": "user", "content": user_prompt}],
        )
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "record_findings":
                return _parse_tool_input(block.input)
        return LLMResult(
            passed=False,
            findings=(LLMFinding(message="LLM returned no structured output."),),
        )

    @staticmethod
    def _is_transient(exc: Exception) -> bool:
        name = type(exc).__name__.lower()
        return any(s in name for s in ("rate", "timeout", "connection", "apiconnection"))

    @staticmethod
    def _cache_key(rule_id: str, system_prompt: str, user_prompt: str) -> str:
        h = hashlib.sha256()
        h.update(rule_id.encode())
        h.update(b"\x00")
        h.update(system_prompt.encode())
        h.update(b"\x00")
        h.update(user_prompt.encode())
        return h.hexdigest()


def _parse_tool_input(payload: object) -> LLMResult:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return LLMResult(
                passed=False,
                findings=(LLMFinding(message="LLM returned malformed JSON."),),
            )
    if not isinstance(payload, Mapping):
        return LLMResult(
            passed=False,
            findings=(LLMFinding(message="LLM returned unexpected payload type."),),
        )
    findings_raw = payload.get("findings", [])
    if not isinstance(findings_raw, list):
        findings_raw = []
    findings = tuple(
        LLMFinding(
            message=str(item.get("message", "")).strip()
            or "Section did not meet the rule (LLM provided no detail).",
            evidence=(str(item.get("evidence")).strip() or None) if item.get("evidence") else None,
        )
        for item in findings_raw
        if isinstance(item, Mapping)
    )
    passed = bool(payload.get("passed", len(findings) == 0))
    return LLMResult(passed=passed, findings=findings)
