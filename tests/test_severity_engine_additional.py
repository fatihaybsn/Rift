"""Additional severity rule branch tests."""

from __future__ import annotations

from app.core.diff_engine import (
    CompatibilityClassification,
    ConfidenceLevel,
    DiffFinding,
    FindingCategory,
    FindingCode,
    LocationMarker,
)
from app.core.severity_engine import SeverityLevel, classify_finding_severity


def _finding(code: FindingCode, compatibility: CompatibilityClassification) -> DiffFinding:
    return DiffFinding(
        category=FindingCategory.SECURITY,
        code=code,
        path="/x",
        method="get",
        location="auth",
        entity_path="/x#get",
        field_path=None,
        location_marker=LocationMarker.AUTH,
        locator="auth:/x#get",
        compatibility=compatibility,
        confidence=ConfidenceLevel.HIGH,
        before=None,
        after=None,
        sort_key=f"{code.value}|{compatibility.value}",
    )


def test_security_scheme_removed_is_high() -> None:
    decision = classify_finding_severity(
        _finding(FindingCode.SECURITY_SCHEME_REMOVED, CompatibilityClassification.BREAKING)
    )
    assert decision.severity is SeverityLevel.HIGH


def test_request_field_added_non_breaking_uses_fallback_low() -> None:
    decision = classify_finding_severity(
        _finding(FindingCode.REQUEST_FIELD_ADDED, CompatibilityClassification.NON_BREAKING)
    )
    assert decision.severity is SeverityLevel.LOW
    assert "non-breaking" in decision.explanation


def test_response_field_added_ignores_compatibility_and_stays_low() -> None:
    decision = classify_finding_severity(
        _finding(FindingCode.RESPONSE_FIELD_ADDED, CompatibilityClassification.BREAKING)
    )
    assert decision.severity is SeverityLevel.LOW
