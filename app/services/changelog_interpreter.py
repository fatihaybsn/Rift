"""Optional AI changelog interpreter abstractions and defaults."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ChangelogProviderError(RuntimeError):
    """Raised when provider execution fails or returns unusable output."""


@dataclass(frozen=True)
class ChangelogTaskSuggestion:
    """One AI-suggested migration task from changelog interpretation."""

    title: str
    detail: str
    priority: int


@dataclass(frozen=True)
class ChangelogInterpretationResult:
    """Typed provider result used by orchestration mapping logic."""

    summary: str
    migration_tasks: tuple[ChangelogTaskSuggestion, ...]
    confidence: float
    explanation: str
    requires_manual_review: bool
    provider: str
    model: str


class ChangelogPromptBuilder:
    """Build explicit prompts for optional changelog interpretation."""

    def build_prompt(
        self,
        *,
        changelog_text: str,
    ) -> str:
        return (
            "You are assisting API Change Radar. Interpret changelog text only.\n"
            "Return:\n"
            "- concise summary\n"
            "- migration task suggestions\n"
            "- confidence in [0,1]\n"
            "- explanation for confidence\n"
            "- whether AI output itself needs manual review\n"
            "Do NOT infer deterministic findings, severities, or run lifecycle state.\n\n"
            f"Changelog:\n{changelog_text}"
        )


class ChangelogInterpretationProvider(Protocol):
    """Provider adapter protocol for mockable LLM integrations."""

    def interpret(
        self,
        *,
        prompt: str,
        changelog_text: str,
    ) -> ChangelogInterpretationResult:
        """Interpret changelog text and return optional enrichment output."""


class NoLLMChangelogProvider:
    """Safe fallback adapter used when no external LLM provider is configured."""

    def interpret(
        self,
        *,
        prompt: str,
        changelog_text: str,
    ) -> ChangelogInterpretationResult:
        del prompt, changelog_text
        return ChangelogInterpretationResult(
            summary="No LLM provider configured.",
            migration_tasks=(),
            confidence=0.0,
            explanation="AI enrichment fallback mode is active.",
            requires_manual_review=True,
            provider="none",
            model="none",
        )


__all__ = [
    "ChangelogProviderError",
    "ChangelogInterpretationProvider",
    "ChangelogInterpretationResult",
    "ChangelogPromptBuilder",
    "ChangelogTaskSuggestion",
    "NoLLMChangelogProvider",
]
