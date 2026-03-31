"""Unit tests for deterministic canonical diff engine."""

from __future__ import annotations

import pytest

from app.core.diff_engine import (
    CompatibilityClassification,
    DiffEngineError,
    FindingCategory,
    FindingCode,
    diff_canonical_snapshots,
)
from app.core.openapi_processing import (
    CanonicalOpenAPISnapshot,
    CanonicalOperation,
    CanonicalRequestBody,
    CanonicalResponse,
    CanonicalSchema,
)
from tests.fixtures.diff_snapshots import (
    build_composition_change_snapshots,
    build_operation_surface_snapshots,
    build_parameter_change_snapshots,
    build_request_body_presence_snapshots,
    build_request_body_removed_snapshots,
    build_request_change_snapshots,
    build_response_change_snapshots,
    build_security_change_snapshots,
)


def _codes(findings) -> set[FindingCode]:
    return {finding.code for finding in findings}


def _find_one(findings, code: FindingCode):
    matches = [item for item in findings if item.code == code]
    assert matches, f"expected finding code {code.value}"
    return matches[0]


def test_operation_surface_changes_are_detected() -> None:
    old_snapshot, new_snapshot = build_operation_surface_snapshots()

    findings = diff_canonical_snapshots(old_snapshot, new_snapshot)
    codes = _codes(findings)

    assert FindingCode.PATH_ADDED in codes
    assert FindingCode.PATH_REMOVED in codes
    assert FindingCode.METHOD_ADDED in codes
    assert FindingCode.METHOD_REMOVED in codes
    assert FindingCode.OPERATION_DEPRECATED_CHANGED in codes


def test_parameter_changes_are_detected() -> None:
    old_snapshot, new_snapshot = build_parameter_change_snapshots()

    findings = diff_canonical_snapshots(old_snapshot, new_snapshot)
    codes = _codes(findings)

    assert FindingCode.PARAMETER_ADDED in codes
    assert FindingCode.PARAMETER_REQUIRED_CHANGED in codes
    assert FindingCode.PARAMETER_SCHEMA_CHANGED in codes
    assert FindingCode.PARAMETER_LOCATION_CHANGED in codes
    assert FindingCode.PARAMETER_OVERRIDE_EFFECT_CHANGED in codes


def test_request_changes_are_detected() -> None:
    old_snapshot, new_snapshot = build_request_change_snapshots()

    findings = diff_canonical_snapshots(old_snapshot, new_snapshot)
    codes = _codes(findings)

    assert FindingCode.REQUEST_BODY_REQUIRED_CHANGED in codes
    assert FindingCode.REQUEST_MEDIA_TYPE_ADDED in codes
    assert FindingCode.REQUEST_MEDIA_TYPE_REMOVED in codes
    assert FindingCode.REQUEST_FIELD_ADDED in codes
    assert FindingCode.REQUEST_FIELD_TYPE_CHANGED in codes
    assert FindingCode.REQUEST_ENUM_SHRUNK in codes
    assert FindingCode.REQUEST_NULLABLE_CHANGED in codes
    assert FindingCode.REQUEST_READ_WRITE_EFFECT_CHANGED in codes
    assert FindingCode.REQUEST_ADDITIONAL_PROPERTIES_CHANGED in codes


def test_request_body_added_and_removed_are_detected() -> None:
    old_snapshot, new_snapshot = build_request_body_presence_snapshots()
    added_findings = diff_canonical_snapshots(old_snapshot, new_snapshot)
    assert FindingCode.REQUEST_BODY_ADDED in _codes(added_findings)

    old_snapshot, new_snapshot = build_request_body_removed_snapshots()
    removed_findings = diff_canonical_snapshots(old_snapshot, new_snapshot)
    assert FindingCode.REQUEST_BODY_REMOVED in _codes(removed_findings)


def test_response_changes_are_detected() -> None:
    old_snapshot, new_snapshot = build_response_change_snapshots()

    findings = diff_canonical_snapshots(old_snapshot, new_snapshot)
    codes = _codes(findings)

    assert FindingCode.RESPONSE_STATUS_ADDED in codes
    assert FindingCode.RESPONSE_STATUS_REMOVED in codes
    assert FindingCode.RESPONSE_DEFAULT_REMOVED in codes
    assert FindingCode.RESPONSE_MEDIA_TYPE_ADDED in codes
    assert FindingCode.RESPONSE_MEDIA_TYPE_REMOVED in codes
    assert FindingCode.RESPONSE_FIELD_ADDED in codes
    assert FindingCode.RESPONSE_FIELD_REMOVED in codes
    assert FindingCode.RESPONSE_FIELD_TYPE_CHANGED in codes
    assert FindingCode.RESPONSE_ENUM_WIDENED in codes
    assert FindingCode.RESPONSE_NULLABLE_CHANGED in codes
    assert FindingCode.RESPONSE_READ_WRITE_EFFECT_CHANGED in codes
    assert FindingCode.RESPONSE_ADDITIONAL_PROPERTIES_CHANGED in codes


def test_reverse_diff_detects_opposite_enum_and_default_transitions() -> None:
    old_request, new_request = build_request_change_snapshots()
    reversed_request_findings = diff_canonical_snapshots(new_request, old_request)
    reversed_request_codes = _codes(reversed_request_findings)
    assert FindingCode.REQUEST_ENUM_WIDENED in reversed_request_codes

    old_response, new_response = build_response_change_snapshots()
    reversed_response_findings = diff_canonical_snapshots(new_response, old_response)
    reversed_response_codes = _codes(reversed_response_findings)
    assert FindingCode.RESPONSE_DEFAULT_ADDED in reversed_response_codes
    assert FindingCode.RESPONSE_ENUM_SHRUNK in reversed_response_codes


def test_security_changes_are_detected() -> None:
    old_snapshot, new_snapshot = build_security_change_snapshots()

    findings = diff_canonical_snapshots(old_snapshot, new_snapshot)
    codes = _codes(findings)

    assert FindingCode.SECURITY_TOP_LEVEL_CHANGED in codes
    assert FindingCode.SECURITY_OPERATION_CHANGED in codes
    assert FindingCode.SECURITY_SCHEME_ADDED in codes
    assert FindingCode.SECURITY_SCHEME_REMOVED in codes
    assert FindingCode.SECURITY_SCHEME_CHANGED in codes


def test_composition_changes_are_detected() -> None:
    old_snapshot, new_snapshot = build_composition_change_snapshots()

    findings = diff_canonical_snapshots(old_snapshot, new_snapshot)
    codes = _codes(findings)

    assert FindingCode.COMPOSITION_ALLOF_CHANGED in codes
    assert FindingCode.COMPOSITION_ONEOF_CHANGED in codes
    assert FindingCode.COMPOSITION_ANYOF_CHANGED in codes
    assert FindingCode.COMPOSITION_DISCRIMINATOR_CHANGED in codes


def test_stable_ordering_is_deterministic_across_runs() -> None:
    old_snapshot, new_snapshot = build_request_change_snapshots()

    findings_a = diff_canonical_snapshots(old_snapshot, new_snapshot)
    findings_b = diff_canonical_snapshots(old_snapshot, new_snapshot)

    assert [item.sort_key for item in findings_a] == sorted(item.sort_key for item in findings_a)
    assert [item.to_dict() for item in findings_a] == [item.to_dict() for item in findings_b]


def test_media_type_differences_are_explicit_for_request_and_response() -> None:
    old_request, new_request = build_request_change_snapshots()
    request_findings = diff_canonical_snapshots(old_request, new_request)
    assert FindingCode.REQUEST_MEDIA_TYPE_ADDED in _codes(request_findings)
    assert FindingCode.REQUEST_MEDIA_TYPE_REMOVED in _codes(request_findings)

    old_response, new_response = build_response_change_snapshots()
    response_findings = diff_canonical_snapshots(old_response, new_response)
    assert FindingCode.RESPONSE_MEDIA_TYPE_ADDED in _codes(response_findings)
    assert FindingCode.RESPONSE_MEDIA_TYPE_REMOVED in _codes(response_findings)


def test_readonly_writeonly_directionality_changes_are_explicit() -> None:
    old_snapshot, new_snapshot = build_request_change_snapshots()
    findings = diff_canonical_snapshots(old_snapshot, new_snapshot)
    request_effect = _find_one(findings, FindingCode.REQUEST_READ_WRITE_EFFECT_CHANGED)
    assert request_effect.location == "request"
    assert request_effect.locator.startswith("request:")

    old_snapshot, new_snapshot = build_response_change_snapshots()
    findings = diff_canonical_snapshots(old_snapshot, new_snapshot)
    response_effect = _find_one(findings, FindingCode.RESPONSE_READ_WRITE_EFFECT_CHANGED)
    assert response_effect.location == "response"
    assert response_effect.locator.startswith("response:")


def test_machine_readable_fields_and_typed_category_are_present() -> None:
    old_snapshot, new_snapshot = build_operation_surface_snapshots()
    findings = diff_canonical_snapshots(old_snapshot, new_snapshot)
    finding = findings[0]
    payload = finding.to_dict()

    assert isinstance(finding.category, FindingCategory)
    assert "path" in payload
    assert "method" in payload
    assert "location" in payload
    assert "entity_path" in payload
    assert "field_path" in payload
    assert "before" in payload
    assert "after" in payload
    assert payload["location_marker"] in {"operation", "parameter", "request", "response", "auth"}
    assert payload["location"] in {"operation", "parameter", "request", "response", "auth"}
    assert "locator" in payload
    assert payload["compatibility"] in {
        "breaking",
        "potentially_breaking",
        "non_breaking",
        "unknown",
    }
    assert payload["confidence"] in {"high", "medium", "low"}
    assert payload["sort_key"] == finding.sort_key


def test_finding_model_parses_path_method_entity_and_field_paths() -> None:
    old_snapshot, new_snapshot = build_request_change_snapshots()
    findings = diff_canonical_snapshots(old_snapshot, new_snapshot)

    media_removed = _find_one(findings, FindingCode.REQUEST_MEDIA_TYPE_REMOVED)
    assert media_removed.path == "/users"
    assert media_removed.method == "post"
    assert media_removed.location == "request"
    assert media_removed.entity_path == "/users#post#application/xml"
    assert media_removed.field_path is None

    field_changed = _find_one(findings, FindingCode.REQUEST_FIELD_TYPE_CHANGED)
    assert field_changed.path == "/users"
    assert field_changed.method == "post"
    assert field_changed.location == "request"
    assert field_changed.entity_path is not None
    assert field_changed.field_path is not None
    assert field_changed.field_path.startswith("/properties/")


def test_path_level_finding_exposes_path_without_method() -> None:
    old_snapshot, new_snapshot = build_operation_surface_snapshots()
    findings = diff_canonical_snapshots(old_snapshot, new_snapshot)
    path_added = _find_one(findings, FindingCode.PATH_ADDED)

    assert path_added.path == "/teams"
    assert path_added.method is None
    assert path_added.location == "operation"
    assert path_added.entity_path == "/teams"
    assert path_added.field_path is None


def test_compatibility_classification_examples() -> None:
    old_snapshot, new_snapshot = build_request_body_presence_snapshots()
    findings = diff_canonical_snapshots(old_snapshot, new_snapshot)
    added_body = _find_one(findings, FindingCode.REQUEST_BODY_ADDED)
    assert added_body.compatibility is CompatibilityClassification.BREAKING

    old_snapshot, new_snapshot = build_operation_surface_snapshots()
    findings = diff_canonical_snapshots(old_snapshot, new_snapshot)
    removed_method = _find_one(findings, FindingCode.METHOD_REMOVED)
    assert removed_method.compatibility is CompatibilityClassification.BREAKING


def test_byte_stable_serialization_for_same_inputs() -> None:
    import json

    old_snapshot, new_snapshot = build_response_change_snapshots()
    findings_a = diff_canonical_snapshots(old_snapshot, new_snapshot)
    findings_b = diff_canonical_snapshots(old_snapshot, new_snapshot)

    serialized_a = json.dumps(
        [item.to_dict() for item in findings_a],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    serialized_b = json.dumps(
        [item.to_dict() for item in findings_b],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert serialized_a == serialized_b


def test_diff_fails_on_schema_version_mismatch() -> None:
    old_snapshot, new_snapshot = build_operation_surface_snapshots()
    mutated_new = CanonicalOpenAPISnapshot(
        schema_version="v2",
        openapi_version=new_snapshot.openapi_version,
        top_level_security=new_snapshot.top_level_security,
        security_schemes=new_snapshot.security_schemes,
        operations=new_snapshot.operations,
    )

    with pytest.raises(DiffEngineError, match="unsupported canonical structure"):
        diff_canonical_snapshots(old_snapshot, mutated_new)


def test_diff_fails_on_duplicate_operation_identity() -> None:
    old_snapshot, new_snapshot = build_operation_surface_snapshots()
    duplicated_operation = old_snapshot.operations[0]
    mutated_old = CanonicalOpenAPISnapshot(
        schema_version=old_snapshot.schema_version,
        openapi_version=old_snapshot.openapi_version,
        top_level_security=old_snapshot.top_level_security,
        security_schemes=old_snapshot.security_schemes,
        operations=(duplicated_operation, duplicated_operation),
    )

    with pytest.raises(DiffEngineError, match="duplicate operation identity"):
        diff_canonical_snapshots(mutated_old, new_snapshot)


def test_diff_fails_on_duplicate_parameter_identity_in_operation() -> None:
    old_snapshot, new_snapshot = build_parameter_change_snapshots()
    operation = old_snapshot.operations[0]
    duplicated_parameter = operation.parameters[0]
    mutated_operation = CanonicalOperation(
        path=operation.path,
        method=operation.method,
        operation_id=operation.operation_id,
        deprecated=operation.deprecated,
        parameters=(duplicated_parameter, duplicated_parameter),
        request_body=operation.request_body,
        responses=operation.responses,
        security_override=operation.security_override,
    )
    mutated_old = CanonicalOpenAPISnapshot(
        schema_version=old_snapshot.schema_version,
        openapi_version=old_snapshot.openapi_version,
        top_level_security=old_snapshot.top_level_security,
        security_schemes=old_snapshot.security_schemes,
        operations=(mutated_operation,),
    )

    with pytest.raises(DiffEngineError, match="duplicate parameter identity"):
        diff_canonical_snapshots(mutated_old, new_snapshot)


def test_diff_fails_on_invalid_canonical_schema_node_type() -> None:
    old_snapshot, new_snapshot = build_request_change_snapshots()
    operation = old_snapshot.operations[0]
    media = operation.request_body.media_types[0]
    invalid_schema = CanonicalSchema(
        type=media.schema.type,
        format=media.schema.format,
        enum=media.schema.enum,
        nullable=media.schema.nullable,
        required=media.schema.required,
        properties=media.schema.properties,
        items=media.schema.items,
        additional_properties="invalid",  # type: ignore[arg-type]
        read_only=media.schema.read_only,
        write_only=media.schema.write_only,
        deprecated=media.schema.deprecated,
        all_of=media.schema.all_of,
        one_of=media.schema.one_of,
        any_of=media.schema.any_of,
        discriminator=media.schema.discriminator,
    )
    mutated_request = CanonicalRequestBody(
        present=operation.request_body.present,
        required=operation.request_body.required,
        media_types=((type(media))(media_type=media.media_type, schema=invalid_schema),),
    )
    mutated_operation = CanonicalOperation(
        path=operation.path,
        method=operation.method,
        operation_id=operation.operation_id,
        deprecated=operation.deprecated,
        parameters=operation.parameters,
        request_body=mutated_request,
        responses=operation.responses,
        security_override=operation.security_override,
    )
    mutated_old = CanonicalOpenAPISnapshot(
        schema_version=old_snapshot.schema_version,
        openapi_version=old_snapshot.openapi_version,
        top_level_security=old_snapshot.top_level_security,
        security_schemes=old_snapshot.security_schemes,
        operations=(mutated_operation,),
    )

    with pytest.raises(DiffEngineError, match="unsupported canonical structure"):
        diff_canonical_snapshots(mutated_old, new_snapshot)


def test_diff_fails_on_duplicate_response_status_keys() -> None:
    old_snapshot, new_snapshot = build_response_change_snapshots()
    operation = old_snapshot.operations[0]
    duplicated_response = operation.responses[0]
    mutated_operation = CanonicalOperation(
        path=operation.path,
        method=operation.method,
        operation_id=operation.operation_id,
        deprecated=operation.deprecated,
        parameters=operation.parameters,
        request_body=operation.request_body,
        responses=(duplicated_response, duplicated_response),
        security_override=operation.security_override,
    )
    mutated_old = CanonicalOpenAPISnapshot(
        schema_version=old_snapshot.schema_version,
        openapi_version=old_snapshot.openapi_version,
        top_level_security=old_snapshot.top_level_security,
        security_schemes=old_snapshot.security_schemes,
        operations=(mutated_operation,),
    )

    with pytest.raises(DiffEngineError, match="duplicate response status"):
        diff_canonical_snapshots(mutated_old, new_snapshot)


def test_diff_fails_on_duplicate_response_media_type_keys() -> None:
    old_snapshot, new_snapshot = build_response_change_snapshots()
    operation = old_snapshot.operations[0]
    response = operation.responses[0]
    media = response.media_types[0]
    mutated_response = CanonicalResponse(
        status_code=response.status_code,
        media_types=(media, media),
    )
    mutated_operation = CanonicalOperation(
        path=operation.path,
        method=operation.method,
        operation_id=operation.operation_id,
        deprecated=operation.deprecated,
        parameters=operation.parameters,
        request_body=operation.request_body,
        responses=(mutated_response,),
        security_override=operation.security_override,
    )
    mutated_old = CanonicalOpenAPISnapshot(
        schema_version=old_snapshot.schema_version,
        openapi_version=old_snapshot.openapi_version,
        top_level_security=old_snapshot.top_level_security,
        security_schemes=old_snapshot.security_schemes,
        operations=(mutated_operation,),
    )

    with pytest.raises(DiffEngineError, match="duplicate response media type"):
        diff_canonical_snapshots(mutated_old, new_snapshot)


def test_diff_fails_on_duplicate_request_media_type_keys() -> None:
    old_snapshot, new_snapshot = build_request_change_snapshots()
    operation = old_snapshot.operations[0]
    media = operation.request_body.media_types[0]
    mutated_request_body = CanonicalRequestBody(
        present=operation.request_body.present,
        required=operation.request_body.required,
        media_types=(media, media),
    )
    mutated_operation = CanonicalOperation(
        path=operation.path,
        method=operation.method,
        operation_id=operation.operation_id,
        deprecated=operation.deprecated,
        parameters=operation.parameters,
        request_body=mutated_request_body,
        responses=operation.responses,
        security_override=operation.security_override,
    )
    mutated_old = CanonicalOpenAPISnapshot(
        schema_version=old_snapshot.schema_version,
        openapi_version=old_snapshot.openapi_version,
        top_level_security=old_snapshot.top_level_security,
        security_schemes=old_snapshot.security_schemes,
        operations=(mutated_operation,),
    )

    with pytest.raises(DiffEngineError, match="duplicate request media type"):
        diff_canonical_snapshots(mutated_old, new_snapshot)
