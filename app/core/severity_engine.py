"""Deterministic severity rules for canonical diff findings."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from app.core.diff_engine import CompatibilityClassification, DiffFinding, FindingCode


class SeverityLevel(StrEnum):
    """Supported severity labels for deterministic findings."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class SeverityDecision:
    """Severity output for a single finding."""

    severity: SeverityLevel
    explanation: str


@dataclass(frozen=True)
class ClassifiedFinding:
    """Finding plus deterministic severity decision."""

    finding: DiffFinding
    severity: SeverityLevel
    explanation: str


_COMPATIBILITY_FALLBACK: dict[CompatibilityClassification, SeverityDecision] = {
    CompatibilityClassification.BREAKING: SeverityDecision(
        severity=SeverityLevel.HIGH,
        explanation="Marked high because deterministic compatibility is breaking.",
    ),
    CompatibilityClassification.POTENTIALLY_BREAKING: SeverityDecision(
        severity=SeverityLevel.MEDIUM,
        explanation="Marked medium because deterministic compatibility may break clients.",
    ),
    CompatibilityClassification.NON_BREAKING: SeverityDecision(
        severity=SeverityLevel.LOW,
        explanation="Marked low because deterministic compatibility is non-breaking.",
    ),
    CompatibilityClassification.UNKNOWN: SeverityDecision(
        severity=SeverityLevel.MEDIUM,
        explanation="Marked medium because deterministic compatibility impact is unknown.",
    ),
}


def classify_finding_severity(finding: DiffFinding) -> SeverityDecision:
    """Classify a finding with explicit deterministic MVP severity defaults."""
    # Endpoint removals are high because a previously reachable contract disappears.
    if finding.code in {FindingCode.PATH_REMOVED, FindingCode.METHOD_REMOVED}:
        return SeverityDecision(
            severity=SeverityLevel.HIGH,
            explanation="Endpoint removal is a breaking API surface change.",
        )

    # Request field additions become high only when the diff marks them as newly required.
    if (
        finding.code == FindingCode.REQUEST_FIELD_ADDED
        and finding.compatibility == CompatibilityClassification.BREAKING
    ):
        return SeverityDecision(
            severity=SeverityLevel.HIGH,
            explanation="A required request field was added.",
        )

    # Additive response fields are treated as low risk in MVP because clients can ignore extras.
    if finding.code == FindingCode.RESPONSE_FIELD_ADDED:
        return SeverityDecision(
            severity=SeverityLevel.LOW,
            explanation="An optional response field was added.",
        )

    # Auth scheme mutations are high because credential negotiation changes at protocol level.
    if finding.code in {FindingCode.SECURITY_SCHEME_CHANGED, FindingCode.SECURITY_SCHEME_REMOVED}:
        return SeverityDecision(
            severity=SeverityLevel.HIGH,
            explanation="Authentication scheme changed.",
        )

    # Enum shrink context model:
    # - request enums: high (existing client inputs may be rejected)
    # - response enums: medium (consumers may rely on removed values)
    if finding.code == FindingCode.REQUEST_ENUM_SHRUNK:
        return SeverityDecision(
            severity=SeverityLevel.HIGH,
            explanation="Request enum was narrowed.",
        )
    if finding.code == FindingCode.RESPONSE_ENUM_SHRUNK:
        return SeverityDecision(
            severity=SeverityLevel.MEDIUM,
            explanation="Response enum was narrowed.",
        )

    return _COMPATIBILITY_FALLBACK[finding.compatibility]


def classify_findings(findings: Iterable[DiffFinding]) -> tuple[ClassifiedFinding, ...]:
    """Classify all findings while preserving the incoming deterministic order."""
    classified: list[ClassifiedFinding] = []
    for finding in findings:
        decision = classify_finding_severity(finding)
        classified.append(
            ClassifiedFinding(
                finding=finding,
                severity=decision.severity,
                explanation=decision.explanation,
            )
        )
    return tuple(classified)


__all__ = [
    "ClassifiedFinding",
    "SeverityDecision",
    "SeverityLevel",
    "classify_finding_severity",
    "classify_findings",
]
