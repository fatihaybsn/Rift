"""Unit tests for deterministic severity classification rules."""

from __future__ import annotations

from app.core.diff_engine import (
    CompatibilityClassification,
    ConfidenceLevel,
    DiffFinding,
    FindingCategory,
    FindingCode,
    LocationMarker,
    diff_canonical_snapshots,
)
from app.core.severity_engine import SeverityLevel, classify_finding_severity, classify_findings
from tests.fixtures_diff_engine import (
    build_operation_surface_snapshots,
    build_request_change_snapshots,
    build_response_change_snapshots,
    build_security_change_snapshots,
)


def _make_finding(
    *,
    code: FindingCode,
    compatibility: CompatibilityClassification,
) -> DiffFinding:
    return DiffFinding(
        category=FindingCategory.OPERATION_SURFACE,
        code=code,
        path="/pets",
        method="get",
        location="operation",
        entity_path="/pets#get",
        field_path=None,
        location_marker=LocationMarker.OPERATION,
        locator="operation:/pets#get",
        compatibility=compatibility,
        confidence=ConfidenceLevel.HIGH,
        before=None,
        after=None,
        sort_key=f"{code.value}|{compatibility.value}",
    )


def test_endpoint_removal_is_classified_high() -> None:
    decision = classify_finding_severity(
        _make_finding(
            code=FindingCode.METHOD_REMOVED,
            compatibility=CompatibilityClassification.BREAKING,
        )
    )

    assert decision.severity is SeverityLevel.HIGH
    assert "Endpoint removal" in decision.explanation


def test_required_request_field_addition_is_classified_high() -> None:
    decision = classify_finding_severity(
        _make_finding(
            code=FindingCode.REQUEST_FIELD_ADDED,
            compatibility=CompatibilityClassification.BREAKING,
        )
    )

    assert decision.severity is SeverityLevel.HIGH
    assert "required request field" in decision.explanation


def test_optional_response_field_addition_is_classified_low() -> None:
    decision = classify_finding_severity(
        _make_finding(
            code=FindingCode.RESPONSE_FIELD_ADDED,
            compatibility=CompatibilityClassification.NON_BREAKING,
        )
    )

    assert decision.severity is SeverityLevel.LOW
    assert "optional response field" in decision.explanation


def test_auth_scheme_change_is_classified_high() -> None:
    decision = classify_finding_severity(
        _make_finding(
            code=FindingCode.SECURITY_SCHEME_CHANGED,
            compatibility=CompatibilityClassification.POTENTIALLY_BREAKING,
        )
    )

    assert decision.severity is SeverityLevel.HIGH
    assert "Authentication scheme changed" in decision.explanation


def test_enum_shrink_uses_context_model_request_high_response_medium() -> None:
    request_decision = classify_finding_severity(
        _make_finding(
            code=FindingCode.REQUEST_ENUM_SHRUNK,
            compatibility=CompatibilityClassification.BREAKING,
        )
    )
    response_decision = classify_finding_severity(
        _make_finding(
            code=FindingCode.RESPONSE_ENUM_SHRUNK,
            compatibility=CompatibilityClassification.BREAKING,
        )
    )

    assert request_decision.severity is SeverityLevel.HIGH
    assert response_decision.severity is SeverityLevel.MEDIUM


def test_fallback_compatibility_mapping_is_explicit() -> None:
    assert classify_finding_severity(
        _make_finding(
            code=FindingCode.METHOD_ADDED,
            compatibility=CompatibilityClassification.NON_BREAKING,
        )
    ).severity is SeverityLevel.LOW
    assert classify_finding_severity(
        _make_finding(
            code=FindingCode.PARAMETER_SCHEMA_CHANGED,
            compatibility=CompatibilityClassification.POTENTIALLY_BREAKING,
        )
    ).severity is SeverityLevel.MEDIUM
    assert classify_finding_severity(
        _make_finding(
            code=FindingCode.PARAMETER_REQUIRED_CHANGED,
            compatibility=CompatibilityClassification.BREAKING,
        )
    ).severity is SeverityLevel.HIGH
    assert classify_finding_severity(
        _make_finding(
            code=FindingCode.COMPOSITION_ONEOF_CHANGED,
            compatibility=CompatibilityClassification.UNKNOWN,
        )
    ).severity is SeverityLevel.MEDIUM


def test_classify_findings_preserves_order_and_adds_explanations() -> None:
    old_snapshot, new_snapshot = build_operation_surface_snapshots()
    findings = diff_canonical_snapshots(old_snapshot, new_snapshot)

    classified = classify_findings(findings)

    assert len(classified) == len(findings)
    assert [item.finding.sort_key for item in classified] == [item.sort_key for item in findings]
    assert all(item.explanation for item in classified)


def test_rules_work_on_real_diff_samples() -> None:
    old_request, new_request = build_request_change_snapshots()
    request_findings = diff_canonical_snapshots(old_request, new_request)
    request_classified = {item.finding.code: item for item in classify_findings(request_findings)}
    assert request_classified[FindingCode.REQUEST_ENUM_SHRUNK].severity is SeverityLevel.HIGH

    old_response, new_response = build_response_change_snapshots()
    response_findings = diff_canonical_snapshots(old_response, new_response)
    response_classified = {item.finding.code: item for item in classify_findings(response_findings)}
    assert response_classified[FindingCode.RESPONSE_FIELD_ADDED].severity is SeverityLevel.LOW

    old_security, new_security = build_security_change_snapshots()
    security_findings = diff_canonical_snapshots(old_security, new_security)
    security_classified = {item.finding.code: item for item in classify_findings(security_findings)}
    assert security_classified[FindingCode.SECURITY_SCHEME_CHANGED].severity is SeverityLevel.HIGH
