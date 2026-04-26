"""Structured models for CAE request filtering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(slots=True)
class CAEFilterDecision:
    """Decision emitted by the CAE request guardrail."""

    action: Literal["allow", "deny"]
    reason: str
    classifier: Literal["disabled", "bypass", "rule", "llm", "fallback"]
    category: str = ""
    confidence: float | None = None
    matched_terms: list[str] = field(default_factory=list)
