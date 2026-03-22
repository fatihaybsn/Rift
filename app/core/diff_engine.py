"""Deterministic diff engine over canonical OpenAPI snapshots."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from app.core.openapi_processing import (
    HTTP_METHODS,
    CanonicalOpenAPISnapshot,
    CanonicalOperation,
    CanonicalParameter,
    CanonicalSchema,
    CanonicalSchemaProperty,
    CanonicalSecurityRequirement,
)

SchemaSide = Literal["request", "response"]


class DiffEngineError(ValueError):
    """Raised when canonical snapshots cannot be diffed safely."""


class FindingCategory(StrEnum):
    """Typed high-level finding families."""

    OPERATION_SURFACE = "operation_surface"
    PARAMETER = "parameter"
    REQUEST = "request"
    RESPONSE = "response"
    SECURITY = "security"
    COMPOSITION = "composition"


class FindingCode(StrEnum):
    """Typed deterministic finding codes."""

    PATH_ADDED = "path_added"
    PATH_REMOVED = "path_removed"
    METHOD_ADDED = "method_added"
    METHOD_REMOVED = "method_removed"
    OPERATION_DEPRECATED_CHANGED = "operation_deprecated_changed"
    PARAMETER_ADDED = "parameter_added"
    PARAMETER_REMOVED = "parameter_removed"
    PARAMETER_REQUIRED_CHANGED = "parameter_required_changed"
    PARAMETER_SCHEMA_CHANGED = "parameter_schema_changed"
    PARAMETER_LOCATION_CHANGED = "parameter_location_changed"
    PARAMETER_OVERRIDE_EFFECT_CHANGED = "parameter_override_effect_changed"
    REQUEST_BODY_ADDED = "request_body_added"
    REQUEST_BODY_REMOVED = "request_body_removed"
    REQUEST_BODY_REQUIRED_CHANGED = "request_body_required_changed"
    REQUEST_MEDIA_TYPE_ADDED = "request_media_type_added"
    REQUEST_MEDIA_TYPE_REMOVED = "request_media_type_removed"
    REQUEST_FIELD_ADDED = "request_field_added"
    REQUEST_FIELD_REMOVED = "request_field_removed"
    REQUEST_FIELD_TYPE_CHANGED = "request_field_type_changed"
    REQUEST_ENUM_SHRUNK = "request_enum_shrunk"
    REQUEST_ENUM_WIDENED = "request_enum_widened"
    REQUEST_NULLABLE_CHANGED = "request_nullable_changed"
    REQUEST_READ_WRITE_EFFECT_CHANGED = "request_read_write_effect_changed"
    REQUEST_ADDITIONAL_PROPERTIES_CHANGED = "request_additional_properties_changed"
    RESPONSE_STATUS_ADDED = "response_status_added"
    RESPONSE_STATUS_REMOVED = "response_status_removed"
    RESPONSE_DEFAULT_ADDED = "response_default_added"
    RESPONSE_DEFAULT_REMOVED = "response_default_removed"
    RESPONSE_MEDIA_TYPE_ADDED = "response_media_type_added"
    RESPONSE_MEDIA_TYPE_REMOVED = "response_media_type_removed"
    RESPONSE_FIELD_ADDED = "response_field_added"
    RESPONSE_FIELD_REMOVED = "response_field_removed"
    RESPONSE_FIELD_TYPE_CHANGED = "response_field_type_changed"
    RESPONSE_ENUM_SHRUNK = "response_enum_shrunk"
    RESPONSE_ENUM_WIDENED = "response_enum_widened"
    RESPONSE_NULLABLE_CHANGED = "response_nullable_changed"
    RESPONSE_READ_WRITE_EFFECT_CHANGED = "response_read_write_effect_changed"
    RESPONSE_ADDITIONAL_PROPERTIES_CHANGED = "response_additional_properties_changed"
    SECURITY_TOP_LEVEL_CHANGED = "security_top_level_changed"
    SECURITY_OPERATION_CHANGED = "security_operation_changed"
    SECURITY_SCHEME_ADDED = "security_scheme_added"
    SECURITY_SCHEME_REMOVED = "security_scheme_removed"
    SECURITY_SCHEME_CHANGED = "security_scheme_changed"
    COMPOSITION_ALLOF_CHANGED = "composition_allof_changed"
    COMPOSITION_ONEOF_CHANGED = "composition_oneof_changed"
    COMPOSITION_ANYOF_CHANGED = "composition_anyof_changed"
    COMPOSITION_DISCRIMINATOR_CHANGED = "composition_discriminator_changed"


class LocationMarker(StrEnum):
    """Explicit finding area markers."""

    OPERATION = "operation"
    PARAMETER = "parameter"
    REQUEST = "request"
    RESPONSE = "response"
    AUTH = "auth"


class CompatibilityClassification(StrEnum):
    """Compatibility impact labels."""

    BREAKING = "breaking"
    POTENTIALLY_BREAKING = "potentially_breaking"
    NON_BREAKING = "non_breaking"
    UNKNOWN = "unknown"


class ConfidenceLevel(StrEnum):
    """Finding confidence labels."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class DiffFinding:
    """Machine-readable deterministic diff finding."""

    category: FindingCategory
    code: FindingCode
    location_marker: LocationMarker
    location: str
    compatibility: CompatibilityClassification
    confidence: ConfidenceLevel
    before: Any | None
    after: Any | None
    sort_key: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize finding payload deterministically."""
        return {
            "category": self.category.value,
            "code": self.code.value,
            "location_marker": self.location_marker.value,
            "location": self.location,
            "compatibility": self.compatibility.value,
            "confidence": self.confidence.value,
            "before": _to_primitive(self.before),
            "after": _to_primitive(self.after),
            "sort_key": self.sort_key,
        }


@dataclass(frozen=True)
class _SchemaDiffContext:
    side: SchemaSide
    base_location: str
    pointer: str


def diff_canonical_snapshots(
    old_snapshot: CanonicalOpenAPISnapshot,
    new_snapshot: CanonicalOpenAPISnapshot,
) -> tuple[DiffFinding, ...]:
    """Produce stable deterministic findings across canonical snapshots."""
    _validate_snapshot(old_snapshot, label="old")
    _validate_snapshot(new_snapshot, label="new")

    if old_snapshot.schema_version != new_snapshot.schema_version:
        raise DiffEngineError(
            "unsupported canonical structure: schema_version mismatch "
            f"({old_snapshot.schema_version!r} != {new_snapshot.schema_version!r})."
        )

    findings: list[DiffFinding] = []
    _diff_operation_surface(old_snapshot, new_snapshot, findings)
    _diff_security(old_snapshot, new_snapshot, findings)
    return tuple(sorted(findings, key=lambda item: item.sort_key))


def _diff_operation_surface(
    old_snapshot: CanonicalOpenAPISnapshot,
    new_snapshot: CanonicalOpenAPISnapshot,
    findings: list[DiffFinding],
) -> None:
    old_operations = {(item.path, item.method): item for item in old_snapshot.operations}
    new_operations = {(item.path, item.method): item for item in new_snapshot.operations}

    old_paths = {path for path, _ in old_operations}
    new_paths = {path for path, _ in new_operations}

    for path in sorted(new_paths - old_paths):
        added_methods = sorted(
            method for current_path, method in new_operations if current_path == path
        )
        _append_finding(
            findings=findings,
            category=FindingCategory.OPERATION_SURFACE,
            code=FindingCode.PATH_ADDED,
            location_marker=LocationMarker.OPERATION,
            location=f"path:{path}",
            compatibility=CompatibilityClassification.NON_BREAKING,
            confidence=ConfidenceLevel.HIGH,
            before=None,
            after={"path": path, "methods": added_methods},
        )

    for path in sorted(old_paths - new_paths):
        removed_methods = sorted(
            method for current_path, method in old_operations if current_path == path
        )
        _append_finding(
            findings=findings,
            category=FindingCategory.OPERATION_SURFACE,
            code=FindingCode.PATH_REMOVED,
            location_marker=LocationMarker.OPERATION,
            location=f"path:{path}",
            compatibility=CompatibilityClassification.BREAKING,
            confidence=ConfidenceLevel.HIGH,
            before={"path": path, "methods": removed_methods},
            after=None,
        )

    shared_paths = sorted(old_paths & new_paths)
    for path in shared_paths:
        old_methods = {method for current_path, method in old_operations if current_path == path}
        new_methods = {method for current_path, method in new_operations if current_path == path}

        for method in sorted(new_methods - old_methods):
            _append_finding(
                findings=findings,
                category=FindingCategory.OPERATION_SURFACE,
                code=FindingCode.METHOD_ADDED,
                location_marker=LocationMarker.OPERATION,
                location=f"operation:{path}#{method}",
                compatibility=CompatibilityClassification.NON_BREAKING,
                confidence=ConfidenceLevel.HIGH,
                before=None,
                after={"path": path, "method": method},
            )
        for method in sorted(old_methods - new_methods):
            _append_finding(
                findings=findings,
                category=FindingCategory.OPERATION_SURFACE,
                code=FindingCode.METHOD_REMOVED,
                location_marker=LocationMarker.OPERATION,
                location=f"operation:{path}#{method}",
                compatibility=CompatibilityClassification.BREAKING,
                confidence=ConfidenceLevel.HIGH,
                before={"path": path, "method": method},
                after=None,
            )

    shared_operations = sorted(old_operations.keys() & new_operations.keys())
    for operation_key in shared_operations:
        old_operation = old_operations[operation_key]
        new_operation = new_operations[operation_key]
        operation_ref = _operation_ref(old_operation.path, old_operation.method)

        if old_operation.deprecated != new_operation.deprecated:
            _append_finding(
                findings=findings,
                category=FindingCategory.OPERATION_SURFACE,
                code=FindingCode.OPERATION_DEPRECATED_CHANGED,
                location_marker=LocationMarker.OPERATION,
                location=f"operation:{operation_ref}",
                compatibility=CompatibilityClassification.NON_BREAKING,
                confidence=ConfidenceLevel.HIGH,
                before={"deprecated": old_operation.deprecated},
                after={"deprecated": new_operation.deprecated},
            )

        _diff_parameters(old_operation, new_operation, findings)
        _diff_request_body(old_operation, new_operation, findings)
        _diff_responses(old_operation, new_operation, findings)


def _diff_parameters(
    old_operation: CanonicalOperation,
    new_operation: CanonicalOperation,
    findings: list[DiffFinding],
) -> None:
    old_by_identity = {item.identity: item for item in old_operation.parameters}
    new_by_identity = {item.identity: item for item in new_operation.parameters}

    shared_identities = sorted(old_by_identity.keys() & new_by_identity.keys())
    removed_identities = set(old_by_identity.keys() - new_by_identity.keys())
    added_identities = set(new_by_identity.keys() - old_by_identity.keys())

    old_only_by_name: dict[str, list[tuple[str, str]]] = defaultdict(list)
    new_only_by_name: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for identity in removed_identities:
        old_only_by_name[identity[0]].append(identity)
    for identity in added_identities:
        new_only_by_name[identity[0]].append(identity)

    for name in sorted(set(old_only_by_name) & set(new_only_by_name)):
        if len(old_only_by_name[name]) != 1 or len(new_only_by_name[name]) != 1:
            continue
        old_identity = old_only_by_name[name][0]
        new_identity = new_only_by_name[name][0]
        old_parameter = old_by_identity[old_identity]
        new_parameter = new_by_identity[new_identity]
        _append_finding(
            findings=findings,
            category=FindingCategory.PARAMETER,
            code=FindingCode.PARAMETER_LOCATION_CHANGED,
            location_marker=LocationMarker.PARAMETER,
            location=f"parameter:{_operation_ref(old_operation.path, old_operation.method)}#{name}",
            compatibility=CompatibilityClassification.BREAKING,
            confidence=ConfidenceLevel.HIGH,
            before=old_parameter.to_dict(),
            after=new_parameter.to_dict(),
        )
        removed_identities.remove(old_identity)
        added_identities.remove(new_identity)

    for identity in sorted(removed_identities):
        removed_parameter = old_by_identity[identity]
        _append_finding(
            findings=findings,
            category=FindingCategory.PARAMETER,
            code=FindingCode.PARAMETER_REMOVED,
            location_marker=LocationMarker.PARAMETER,
            location=_parameter_ref(old_operation.path, old_operation.method, removed_parameter),
            compatibility=CompatibilityClassification.POTENTIALLY_BREAKING,
            confidence=ConfidenceLevel.HIGH,
            before=removed_parameter.to_dict(),
            after=None,
        )

    for identity in sorted(added_identities):
        added_parameter = new_by_identity[identity]
        compatibility = (
            CompatibilityClassification.BREAKING
            if added_parameter.required
            else CompatibilityClassification.NON_BREAKING
        )
        _append_finding(
            findings=findings,
            category=FindingCategory.PARAMETER,
            code=FindingCode.PARAMETER_ADDED,
            location_marker=LocationMarker.PARAMETER,
            location=_parameter_ref(new_operation.path, new_operation.method, added_parameter),
            compatibility=compatibility,
            confidence=ConfidenceLevel.HIGH,
            before=None,
            after=added_parameter.to_dict(),
        )

    for identity in shared_identities:
        old_parameter = old_by_identity[identity]
        new_parameter = new_by_identity[identity]
        parameter_location = _parameter_ref(old_operation.path, old_operation.method, old_parameter)

        required_changed = old_parameter.required != new_parameter.required
        schema_changed = old_parameter.schema != new_parameter.schema

        if required_changed:
            compatibility = (
                CompatibilityClassification.BREAKING
                if old_parameter.required is False and new_parameter.required is True
                else CompatibilityClassification.NON_BREAKING
            )
            _append_finding(
                findings=findings,
                category=FindingCategory.PARAMETER,
                code=FindingCode.PARAMETER_REQUIRED_CHANGED,
                location_marker=LocationMarker.PARAMETER,
                location=parameter_location,
                compatibility=compatibility,
                confidence=ConfidenceLevel.HIGH,
                before={"required": old_parameter.required},
                after={"required": new_parameter.required},
            )

        if schema_changed:
            _append_finding(
                findings=findings,
                category=FindingCategory.PARAMETER,
                code=FindingCode.PARAMETER_SCHEMA_CHANGED,
                location_marker=LocationMarker.PARAMETER,
                location=parameter_location,
                compatibility=CompatibilityClassification.POTENTIALLY_BREAKING,
                confidence=ConfidenceLevel.MEDIUM,
                before=old_parameter.schema.to_dict(),
                after=new_parameter.schema.to_dict(),
            )

        if old_parameter.origin != new_parameter.origin and (required_changed or schema_changed):
            _append_finding(
                findings=findings,
                category=FindingCategory.PARAMETER,
                code=FindingCode.PARAMETER_OVERRIDE_EFFECT_CHANGED,
                location_marker=LocationMarker.PARAMETER,
                location=parameter_location,
                compatibility=CompatibilityClassification.POTENTIALLY_BREAKING,
                confidence=ConfidenceLevel.MEDIUM,
                before={
                    "origin": old_parameter.origin,
                    "required": old_parameter.required,
                    "schema": old_parameter.schema.to_dict(),
                },
                after={
                    "origin": new_parameter.origin,
                    "required": new_parameter.required,
                    "schema": new_parameter.schema.to_dict(),
                },
            )


def _diff_request_body(
    old_operation: CanonicalOperation,
    new_operation: CanonicalOperation,
    findings: list[DiffFinding],
) -> None:
    old_request = old_operation.request_body
    new_request = new_operation.request_body
    operation_ref = _operation_ref(old_operation.path, old_operation.method)
    location_root = f"request:{operation_ref}"

    if old_request.present != new_request.present:
        code = (
            FindingCode.REQUEST_BODY_ADDED
            if new_request.present
            else FindingCode.REQUEST_BODY_REMOVED
        )
        compatibility = (
            CompatibilityClassification.BREAKING
            if code == FindingCode.REQUEST_BODY_ADDED and new_request.required
            else CompatibilityClassification.NON_BREAKING
            if code == FindingCode.REQUEST_BODY_REMOVED
            else CompatibilityClassification.POTENTIALLY_BREAKING
        )
        _append_finding(
            findings=findings,
            category=FindingCategory.REQUEST,
            code=code,
            location_marker=LocationMarker.REQUEST,
            location=location_root,
            compatibility=compatibility,
            confidence=ConfidenceLevel.HIGH,
            before=old_request.to_dict() if old_request.present else None,
            after=new_request.to_dict() if new_request.present else None,
        )

    if not old_request.present or not new_request.present:
        return

    if old_request.required != new_request.required:
        compatibility = (
            CompatibilityClassification.BREAKING
            if old_request.required is False and new_request.required is True
            else CompatibilityClassification.NON_BREAKING
        )
        _append_finding(
            findings=findings,
            category=FindingCategory.REQUEST,
            code=FindingCode.REQUEST_BODY_REQUIRED_CHANGED,
            location_marker=LocationMarker.REQUEST,
            location=location_root,
            compatibility=compatibility,
            confidence=ConfidenceLevel.HIGH,
            before={"required": old_request.required},
            after={"required": new_request.required},
        )

    old_media = {item.media_type: item for item in old_request.media_types}
    new_media = {item.media_type: item for item in new_request.media_types}

    for media_type in sorted(old_media.keys() - new_media.keys()):
        _append_finding(
            findings=findings,
            category=FindingCategory.REQUEST,
            code=FindingCode.REQUEST_MEDIA_TYPE_REMOVED,
            location_marker=LocationMarker.REQUEST,
            location=f"{location_root}#{media_type}",
            compatibility=CompatibilityClassification.BREAKING,
            confidence=ConfidenceLevel.HIGH,
            before={"media_type": media_type, "schema": old_media[media_type].schema.to_dict()},
            after=None,
        )

    for media_type in sorted(new_media.keys() - old_media.keys()):
        _append_finding(
            findings=findings,
            category=FindingCategory.REQUEST,
            code=FindingCode.REQUEST_MEDIA_TYPE_ADDED,
            location_marker=LocationMarker.REQUEST,
            location=f"{location_root}#{media_type}",
            compatibility=CompatibilityClassification.NON_BREAKING,
            confidence=ConfidenceLevel.HIGH,
            before=None,
            after={"media_type": media_type, "schema": new_media[media_type].schema.to_dict()},
        )

    for media_type in sorted(old_media.keys() & new_media.keys()):
        _diff_schema(
            old_schema=old_media[media_type].schema,
            new_schema=new_media[media_type].schema,
            context=_SchemaDiffContext(
                side="request",
                base_location=f"{location_root}#{media_type}",
                pointer="",
            ),
            findings=findings,
        )


def _diff_responses(
    old_operation: CanonicalOperation,
    new_operation: CanonicalOperation,
    findings: list[DiffFinding],
) -> None:
    old_responses = {item.status_code: item for item in old_operation.responses}
    new_responses = {item.status_code: item for item in new_operation.responses}
    operation_ref = _operation_ref(old_operation.path, old_operation.method)
    location_root = f"response:{operation_ref}"

    for status_code in sorted(old_responses.keys() - new_responses.keys(), key=_status_sort_key):
        code = (
            FindingCode.RESPONSE_DEFAULT_REMOVED
            if status_code == "default"
            else FindingCode.RESPONSE_STATUS_REMOVED
        )
        compatibility = (
            CompatibilityClassification.POTENTIALLY_BREAKING
            if status_code == "default"
            else CompatibilityClassification.BREAKING
        )
        _append_finding(
            findings=findings,
            category=FindingCategory.RESPONSE,
            code=code,
            location_marker=LocationMarker.RESPONSE,
            location=f"{location_root}#{status_code}",
            compatibility=compatibility,
            confidence=ConfidenceLevel.HIGH,
            before=old_responses[status_code].to_dict(),
            after=None,
        )

    for status_code in sorted(new_responses.keys() - old_responses.keys(), key=_status_sort_key):
        code = (
            FindingCode.RESPONSE_DEFAULT_ADDED
            if status_code == "default"
            else FindingCode.RESPONSE_STATUS_ADDED
        )
        _append_finding(
            findings=findings,
            category=FindingCategory.RESPONSE,
            code=code,
            location_marker=LocationMarker.RESPONSE,
            location=f"{location_root}#{status_code}",
            compatibility=CompatibilityClassification.NON_BREAKING,
            confidence=ConfidenceLevel.HIGH,
            before=None,
            after=new_responses[status_code].to_dict(),
        )

    for status_code in sorted(old_responses.keys() & new_responses.keys(), key=_status_sort_key):
        old_response = old_responses[status_code]
        new_response = new_responses[status_code]
        old_media = {item.media_type: item for item in old_response.media_types}
        new_media = {item.media_type: item for item in new_response.media_types}

        for media_type in sorted(old_media.keys() - new_media.keys()):
            _append_finding(
                findings=findings,
                category=FindingCategory.RESPONSE,
                code=FindingCode.RESPONSE_MEDIA_TYPE_REMOVED,
                location_marker=LocationMarker.RESPONSE,
                location=f"{location_root}#{status_code}#{media_type}",
                compatibility=CompatibilityClassification.BREAKING,
                confidence=ConfidenceLevel.HIGH,
                before={"media_type": media_type, "schema": old_media[media_type].schema.to_dict()},
                after=None,
            )

        for media_type in sorted(new_media.keys() - old_media.keys()):
            _append_finding(
                findings=findings,
                category=FindingCategory.RESPONSE,
                code=FindingCode.RESPONSE_MEDIA_TYPE_ADDED,
                location_marker=LocationMarker.RESPONSE,
                location=f"{location_root}#{status_code}#{media_type}",
                compatibility=CompatibilityClassification.NON_BREAKING,
                confidence=ConfidenceLevel.HIGH,
                before=None,
                after={"media_type": media_type, "schema": new_media[media_type].schema.to_dict()},
            )

        for media_type in sorted(old_media.keys() & new_media.keys()):
            _diff_schema(
                old_schema=old_media[media_type].schema,
                new_schema=new_media[media_type].schema,
                context=_SchemaDiffContext(
                    side="response",
                    base_location=f"{location_root}#{status_code}#{media_type}",
                    pointer="",
                ),
                findings=findings,
            )


def _diff_security(
    old_snapshot: CanonicalOpenAPISnapshot,
    new_snapshot: CanonicalOpenAPISnapshot,
    findings: list[DiffFinding],
) -> None:
    if old_snapshot.top_level_security != new_snapshot.top_level_security:
        _append_finding(
            findings=findings,
            category=FindingCategory.SECURITY,
            code=FindingCode.SECURITY_TOP_LEVEL_CHANGED,
            location_marker=LocationMarker.AUTH,
            location="auth:top-level",
            compatibility=CompatibilityClassification.POTENTIALLY_BREAKING,
            confidence=ConfidenceLevel.MEDIUM,
            before=[item.to_dict() for item in old_snapshot.top_level_security],
            after=[item.to_dict() for item in new_snapshot.top_level_security],
        )

    old_operations = {(item.path, item.method): item for item in old_snapshot.operations}
    new_operations = {(item.path, item.method): item for item in new_snapshot.operations}
    for operation_key in sorted(old_operations.keys() & new_operations.keys()):
        old_operation = old_operations[operation_key]
        new_operation = new_operations[operation_key]
        if old_operation.security_override != new_operation.security_override:
            _append_finding(
                findings=findings,
                category=FindingCategory.SECURITY,
                code=FindingCode.SECURITY_OPERATION_CHANGED,
                location_marker=LocationMarker.AUTH,
                location=f"auth:{_operation_ref(old_operation.path, old_operation.method)}",
                compatibility=CompatibilityClassification.POTENTIALLY_BREAKING,
                confidence=ConfidenceLevel.MEDIUM,
                before=_security_payload(old_operation.security_override),
                after=_security_payload(new_operation.security_override),
            )

    old_schemes = {item.name: item for item in old_snapshot.security_schemes}
    new_schemes = {item.name: item for item in new_snapshot.security_schemes}

    for scheme_name in sorted(old_schemes.keys() - new_schemes.keys()):
        _append_finding(
            findings=findings,
            category=FindingCategory.SECURITY,
            code=FindingCode.SECURITY_SCHEME_REMOVED,
            location_marker=LocationMarker.AUTH,
            location=f"auth:scheme:{scheme_name}",
            compatibility=CompatibilityClassification.BREAKING,
            confidence=ConfidenceLevel.HIGH,
            before=old_schemes[scheme_name].to_dict(),
            after=None,
        )

    for scheme_name in sorted(new_schemes.keys() - old_schemes.keys()):
        _append_finding(
            findings=findings,
            category=FindingCategory.SECURITY,
            code=FindingCode.SECURITY_SCHEME_ADDED,
            location_marker=LocationMarker.AUTH,
            location=f"auth:scheme:{scheme_name}",
            compatibility=CompatibilityClassification.NON_BREAKING,
            confidence=ConfidenceLevel.HIGH,
            before=None,
            after=new_schemes[scheme_name].to_dict(),
        )

    for scheme_name in sorted(old_schemes.keys() & new_schemes.keys()):
        old_scheme = old_schemes[scheme_name]
        new_scheme = new_schemes[scheme_name]
        if old_scheme != new_scheme:
            _append_finding(
                findings=findings,
                category=FindingCategory.SECURITY,
                code=FindingCode.SECURITY_SCHEME_CHANGED,
                location_marker=LocationMarker.AUTH,
                location=f"auth:scheme:{scheme_name}",
                compatibility=CompatibilityClassification.POTENTIALLY_BREAKING,
                confidence=ConfidenceLevel.MEDIUM,
                before=old_scheme.to_dict(),
                after=new_scheme.to_dict(),
            )


def _diff_schema(
    *,
    old_schema: CanonicalSchema,
    new_schema: CanonicalSchema,
    context: _SchemaDiffContext,
    findings: list[DiffFinding],
) -> None:
    if old_schema == new_schema:
        return

    location = _schema_location(context.base_location, context.pointer)
    side_category = (
        FindingCategory.REQUEST if context.side == "request" else FindingCategory.RESPONSE
    )
    side_marker = LocationMarker.REQUEST if context.side == "request" else LocationMarker.RESPONSE

    if old_schema.all_of != new_schema.all_of:
        _append_finding(
            findings=findings,
            category=FindingCategory.COMPOSITION,
            code=FindingCode.COMPOSITION_ALLOF_CHANGED,
            location_marker=side_marker,
            location=location,
            compatibility=CompatibilityClassification.UNKNOWN,
            confidence=ConfidenceLevel.MEDIUM,
            before=[item.to_dict() for item in old_schema.all_of],
            after=[item.to_dict() for item in new_schema.all_of],
        )
    if old_schema.one_of != new_schema.one_of:
        _append_finding(
            findings=findings,
            category=FindingCategory.COMPOSITION,
            code=FindingCode.COMPOSITION_ONEOF_CHANGED,
            location_marker=side_marker,
            location=location,
            compatibility=CompatibilityClassification.UNKNOWN,
            confidence=ConfidenceLevel.MEDIUM,
            before=[item.to_dict() for item in old_schema.one_of],
            after=[item.to_dict() for item in new_schema.one_of],
        )
    if old_schema.any_of != new_schema.any_of:
        _append_finding(
            findings=findings,
            category=FindingCategory.COMPOSITION,
            code=FindingCode.COMPOSITION_ANYOF_CHANGED,
            location_marker=side_marker,
            location=location,
            compatibility=CompatibilityClassification.UNKNOWN,
            confidence=ConfidenceLevel.MEDIUM,
            before=[item.to_dict() for item in old_schema.any_of],
            after=[item.to_dict() for item in new_schema.any_of],
        )
    if old_schema.discriminator != new_schema.discriminator:
        _append_finding(
            findings=findings,
            category=FindingCategory.COMPOSITION,
            code=FindingCode.COMPOSITION_DISCRIMINATOR_CHANGED,
            location_marker=side_marker,
            location=location,
            compatibility=CompatibilityClassification.POTENTIALLY_BREAKING,
            confidence=ConfidenceLevel.MEDIUM,
            before=old_schema.discriminator.to_dict() if old_schema.discriminator else None,
            after=new_schema.discriminator.to_dict() if new_schema.discriminator else None,
        )

    if old_schema.type != new_schema.type or old_schema.format != new_schema.format:
        _append_finding(
            findings=findings,
            category=side_category,
            code=_field_type_code(context.side),
            location_marker=side_marker,
            location=location,
            compatibility=_field_type_compatibility(context.side),
            confidence=ConfidenceLevel.HIGH,
            before={"type": old_schema.type, "format": old_schema.format},
            after={"type": new_schema.type, "format": new_schema.format},
        )

    if old_schema.nullable != new_schema.nullable:
        _append_finding(
            findings=findings,
            category=side_category,
            code=_nullable_code(context.side),
            location_marker=side_marker,
            location=location,
            compatibility=_nullable_compatibility(
                context.side, old_schema.nullable, new_schema.nullable
            ),
            confidence=ConfidenceLevel.HIGH,
            before={"nullable": old_schema.nullable},
            after={"nullable": new_schema.nullable},
        )

    _diff_enum_values(old_schema, new_schema, context, findings)
    _diff_additional_properties(old_schema, new_schema, context, findings)
    _diff_properties(old_schema, new_schema, context, findings)

    if old_schema.items is not None and new_schema.items is not None:
        _diff_schema(
            old_schema=old_schema.items,
            new_schema=new_schema.items,
            context=_SchemaDiffContext(
                side=context.side,
                base_location=context.base_location,
                pointer=_join_pointer(context.pointer, "items"),
            ),
            findings=findings,
        )


def _diff_enum_values(
    old_schema: CanonicalSchema,
    new_schema: CanonicalSchema,
    context: _SchemaDiffContext,
    findings: list[DiffFinding],
) -> None:
    if old_schema.enum is None or new_schema.enum is None or old_schema.enum == new_schema.enum:
        return

    old_set = _enum_value_set(old_schema.enum)
    new_set = _enum_value_set(new_schema.enum)
    if new_set < old_set:
        code = _enum_shrunk_code(context.side)
        compatibility = CompatibilityClassification.BREAKING
    elif old_set < new_set:
        code = _enum_widened_code(context.side)
        compatibility = (
            CompatibilityClassification.NON_BREAKING
            if context.side == "request"
            else CompatibilityClassification.POTENTIALLY_BREAKING
        )
    else:
        return

    _append_finding(
        findings=findings,
        category=FindingCategory.REQUEST if context.side == "request" else FindingCategory.RESPONSE,
        code=code,
        location_marker=LocationMarker.REQUEST
        if context.side == "request"
        else LocationMarker.RESPONSE,
        location=_schema_location(context.base_location, context.pointer),
        compatibility=compatibility,
        confidence=ConfidenceLevel.HIGH,
        before={"enum": list(old_schema.enum)},
        after={"enum": list(new_schema.enum)},
    )


def _diff_additional_properties(
    old_schema: CanonicalSchema,
    new_schema: CanonicalSchema,
    context: _SchemaDiffContext,
    findings: list[DiffFinding],
) -> None:
    if old_schema.additional_properties == new_schema.additional_properties:
        return

    old_payload = _additional_properties_payload(old_schema.additional_properties)
    new_payload = _additional_properties_payload(new_schema.additional_properties)
    _append_finding(
        findings=findings,
        category=FindingCategory.REQUEST if context.side == "request" else FindingCategory.RESPONSE,
        code=_additional_properties_code(context.side),
        location_marker=LocationMarker.REQUEST
        if context.side == "request"
        else LocationMarker.RESPONSE,
        location=_schema_location(context.base_location, context.pointer),
        compatibility=_additional_properties_compatibility(
            context.side,
            old_schema.additional_properties,
            new_schema.additional_properties,
        ),
        confidence=ConfidenceLevel.MEDIUM,
        before={"additional_properties": old_payload},
        after={"additional_properties": new_payload},
    )

    if isinstance(old_schema.additional_properties, CanonicalSchema) and isinstance(
        new_schema.additional_properties,
        CanonicalSchema,
    ):
        _diff_schema(
            old_schema=old_schema.additional_properties,
            new_schema=new_schema.additional_properties,
            context=_SchemaDiffContext(
                side=context.side,
                base_location=context.base_location,
                pointer=_join_pointer(context.pointer, "additionalProperties"),
            ),
            findings=findings,
        )


def _diff_properties(
    old_schema: CanonicalSchema,
    new_schema: CanonicalSchema,
    context: _SchemaDiffContext,
    findings: list[DiffFinding],
) -> None:
    old_properties = {item.name: item.schema for item in old_schema.properties}
    new_properties = {item.name: item.schema for item in new_schema.properties}
    property_names = sorted(set(old_properties) | set(new_properties))

    for property_name in property_names:
        old_property = old_properties.get(property_name)
        new_property = new_properties.get(property_name)
        property_pointer = _join_pointer(
            _join_pointer(context.pointer, "properties"), property_name
        )
        property_location = _schema_location(context.base_location, property_pointer)
        side_category = (
            FindingCategory.REQUEST if context.side == "request" else FindingCategory.RESPONSE
        )
        side_marker = (
            LocationMarker.REQUEST if context.side == "request" else LocationMarker.RESPONSE
        )

        if old_property is None and new_property is not None:
            if not _is_effective_property_visible(new_property, context.side):
                continue
            compatibility = _field_added_compatibility(
                context.side,
                property_name in new_schema.required,
            )
            _append_finding(
                findings=findings,
                category=side_category,
                code=_field_added_code(context.side),
                location_marker=side_marker,
                location=property_location,
                compatibility=compatibility,
                confidence=ConfidenceLevel.HIGH,
                before=None,
                after=new_property.to_dict(),
            )
            continue

        if new_property is None and old_property is not None:
            if not _is_effective_property_visible(old_property, context.side):
                continue
            _append_finding(
                findings=findings,
                category=side_category,
                code=_field_removed_code(context.side),
                location_marker=side_marker,
                location=property_location,
                compatibility=_field_removed_compatibility(context.side),
                confidence=ConfidenceLevel.HIGH,
                before=old_property.to_dict(),
                after=None,
            )
            continue

        if old_property is None or new_property is None:
            continue

        old_visible = _is_effective_property_visible(old_property, context.side)
        new_visible = _is_effective_property_visible(new_property, context.side)
        if old_visible != new_visible:
            _append_finding(
                findings=findings,
                category=side_category,
                code=_read_write_effect_code(context.side),
                location_marker=side_marker,
                location=property_location,
                compatibility=_read_write_compatibility(context.side, old_visible, new_visible),
                confidence=ConfidenceLevel.HIGH,
                before={
                    "visible": old_visible,
                    "read_only": old_property.read_only,
                    "write_only": old_property.write_only,
                },
                after={
                    "visible": new_visible,
                    "read_only": new_property.read_only,
                    "write_only": new_property.write_only,
                },
            )
            if not old_visible or not new_visible:
                continue

        if not old_visible and not new_visible:
            continue

        _diff_schema(
            old_schema=old_property,
            new_schema=new_property,
            context=_SchemaDiffContext(
                side=context.side,
                base_location=context.base_location,
                pointer=property_pointer,
            ),
            findings=findings,
        )


def _append_finding(
    *,
    findings: list[DiffFinding],
    category: FindingCategory,
    code: FindingCode,
    location_marker: LocationMarker,
    location: str,
    compatibility: CompatibilityClassification,
    confidence: ConfidenceLevel,
    before: Any | None,
    after: Any | None,
) -> None:
    sort_key = "|".join(
        (
            category.value,
            code.value,
            location_marker.value,
            location,
            _stable_payload_key(before),
            _stable_payload_key(after),
        )
    )
    findings.append(
        DiffFinding(
            category=category,
            code=code,
            location_marker=location_marker,
            location=location,
            compatibility=compatibility,
            confidence=confidence,
            before=_to_primitive(before),
            after=_to_primitive(after),
            sort_key=sort_key,
        )
    )


def _validate_snapshot(snapshot: CanonicalOpenAPISnapshot, *, label: str) -> None:
    if not isinstance(snapshot, CanonicalOpenAPISnapshot):
        raise DiffEngineError(f"unsupported canonical structure: {label} snapshot type is invalid.")

    operation_identities: set[tuple[str, str]] = set()
    for operation in snapshot.operations:
        operation_identity = (operation.path, operation.method)
        if operation_identity in operation_identities:
            raise DiffEngineError(
                "unsupported canonical structure: duplicate operation identity "
                f"{operation_identity!r} in {label} snapshot."
            )
        operation_identities.add(operation_identity)

        if operation.method not in HTTP_METHODS:
            raise DiffEngineError(
                f"unsupported canonical structure: method {operation.method!r} is not supported."
            )

        parameter_identities: set[tuple[str, str]] = set()
        for parameter in operation.parameters:
            if parameter.identity in parameter_identities:
                raise DiffEngineError(
                    "unsupported canonical structure: duplicate parameter identity "
                    f"{parameter.identity!r} in {label} snapshot."
                )
            parameter_identities.add(parameter.identity)
            _validate_schema(
                parameter.schema, context=f"{label}:{operation.path}#{operation.method}:parameter"
            )

        request_media_types = {item.media_type for item in operation.request_body.media_types}
        if len(request_media_types) != len(operation.request_body.media_types):
            raise DiffEngineError(
                "unsupported canonical structure: duplicate request media type "
                f"in {label} snapshot operation {operation.path}#{operation.method}."
            )
        for media in operation.request_body.media_types:
            _validate_schema(
                media.schema,
                context=f"{label}:{operation.path}#{operation.method}:request:{media.media_type}",
            )

        response_statuses = {item.status_code for item in operation.responses}
        if len(response_statuses) != len(operation.responses):
            raise DiffEngineError(
                "unsupported canonical structure: duplicate response status "
                f"in {label} snapshot operation {operation.path}#{operation.method}."
            )
        for response in operation.responses:
            response_media_types = {item.media_type for item in response.media_types}
            if len(response_media_types) != len(response.media_types):
                raise DiffEngineError(
                    "unsupported canonical structure: duplicate response media type "
                    f"in {label} snapshot operation {operation.path}#{operation.method} "
                    f"status {response.status_code}."
                )
            for media in response.media_types:
                _validate_schema(
                    media.schema,
                    context=(
                        f"{label}:{operation.path}#{operation.method}:"
                        f"response:{response.status_code}:{media.media_type}"
                    ),
                )


def _validate_schema(schema: CanonicalSchema, *, context: str) -> None:
    if not isinstance(schema, CanonicalSchema):
        invalid_type = type(schema)
        raise DiffEngineError(
            "unsupported canonical structure: "
            f"{context} schema node has invalid type {invalid_type!r}."
        )
    if schema.type is not None and not isinstance(schema.type, str):
        raise DiffEngineError(
            f"unsupported canonical structure: {context} schema.type must be string/null."
        )
    if not isinstance(schema.nullable, bool):
        raise DiffEngineError(
            f"unsupported canonical structure: {context} schema.nullable must be boolean."
        )
    if schema.enum is not None and not isinstance(schema.enum, tuple):
        raise DiffEngineError(
            f"unsupported canonical structure: {context} schema.enum must be tuple/null."
        )
    if not isinstance(schema.required, tuple):
        raise DiffEngineError(
            f"unsupported canonical structure: {context} schema.required must be tuple."
        )
    if not isinstance(schema.properties, tuple):
        raise DiffEngineError(
            f"unsupported canonical structure: {context} schema.properties must be tuple."
        )
    if not isinstance(schema.additional_properties, (bool, CanonicalSchema)):
        raise DiffEngineError(
            "unsupported canonical structure: "
            f"{context} schema.additional_properties must be boolean or schema."
        )
    if schema.items is not None and not isinstance(schema.items, CanonicalSchema):
        raise DiffEngineError(
            f"unsupported canonical structure: {context} schema.items must be null or schema."
        )
    for collection_name, collection in (
        ("all_of", schema.all_of),
        ("one_of", schema.one_of),
        ("any_of", schema.any_of),
    ):
        if not isinstance(collection, tuple):
            raise DiffEngineError(
                "unsupported canonical structure: "
                f"{context} schema.{collection_name} must be tuple."
            )
        for index, child in enumerate(collection):
            if not isinstance(child, CanonicalSchema):
                raise DiffEngineError(
                    "unsupported canonical structure: "
                    f"{context} schema.{collection_name}[{index}] must be schema."
                )

    for property_entry in schema.properties:
        if not isinstance(property_entry, CanonicalSchemaProperty):
            raise DiffEngineError(
                f"unsupported canonical structure: {context} property entry type is invalid."
            )
        _validate_schema(
            property_entry.schema,
            context=f"{context}.properties.{property_entry.name}",
        )

    if isinstance(schema.additional_properties, CanonicalSchema):
        _validate_schema(schema.additional_properties, context=f"{context}.additional_properties")
    if schema.items is not None:
        _validate_schema(schema.items, context=f"{context}.items")


def _to_primitive(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, CanonicalSchema):
        return value.to_dict()
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if isinstance(value, tuple):
        return [_to_primitive(item) for item in value]
    if isinstance(value, list):
        return [_to_primitive(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_primitive(item) for key, item in value.items()}
    return value


def _stable_payload_key(payload: Any | None) -> str:
    return json.dumps(
        _to_primitive(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _operation_ref(path: str, method: str) -> str:
    return f"{path}#{method}"


def _parameter_ref(path: str, method: str, parameter: CanonicalParameter) -> str:
    return f"parameter:{_operation_ref(path, method)}#{parameter.location}:{parameter.name}"


def _status_sort_key(status_code: str) -> tuple[int, int, str]:
    if status_code == "default":
        return (2, 0, status_code)
    if re.match(r"^[1-5]XX$", status_code):
        return (1, int(status_code[0]), status_code)
    if re.match(r"^[1-5][0-9][0-9]$", status_code):
        return (0, int(status_code), status_code)
    return (3, 0, status_code)


def _security_payload(
    requirements: tuple[CanonicalSecurityRequirement, ...] | None,
) -> list[dict[str, list[str]]] | None:
    if requirements is None:
        return None
    return [item.to_dict() for item in requirements]


def _schema_location(base_location: str, pointer: str) -> str:
    if not pointer:
        return f"{base_location}#"
    return f"{base_location}#{pointer}"


def _join_pointer(pointer: str, segment: str) -> str:
    if not pointer:
        return f"/{segment}"
    return f"{pointer}/{segment}"


def _enum_value_set(enum_values: tuple[Any, ...]) -> set[str]:
    return {
        json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        for item in enum_values
    }


def _is_effective_property_visible(schema: CanonicalSchema, side: SchemaSide) -> bool:
    if side == "request":
        return not schema.read_only
    return not schema.write_only


def _additional_properties_payload(value: bool | CanonicalSchema) -> bool | dict[str, Any]:
    if isinstance(value, bool):
        return value
    return value.to_dict()


def _additional_properties_code(side: SchemaSide) -> FindingCode:
    if side == "request":
        return FindingCode.REQUEST_ADDITIONAL_PROPERTIES_CHANGED
    return FindingCode.RESPONSE_ADDITIONAL_PROPERTIES_CHANGED


def _additional_properties_compatibility(
    side: SchemaSide,
    old_value: bool | CanonicalSchema,
    new_value: bool | CanonicalSchema,
) -> CompatibilityClassification:
    if isinstance(old_value, bool) and isinstance(new_value, bool):
        if side == "request":
            if old_value is True and new_value is False:
                return CompatibilityClassification.BREAKING
            if old_value is False and new_value is True:
                return CompatibilityClassification.NON_BREAKING
        return CompatibilityClassification.POTENTIALLY_BREAKING
    return CompatibilityClassification.POTENTIALLY_BREAKING


def _field_added_code(side: SchemaSide) -> FindingCode:
    return (
        FindingCode.REQUEST_FIELD_ADDED if side == "request" else FindingCode.RESPONSE_FIELD_ADDED
    )


def _field_removed_code(side: SchemaSide) -> FindingCode:
    return (
        FindingCode.REQUEST_FIELD_REMOVED
        if side == "request"
        else FindingCode.RESPONSE_FIELD_REMOVED
    )


def _field_type_code(side: SchemaSide) -> FindingCode:
    return (
        FindingCode.REQUEST_FIELD_TYPE_CHANGED
        if side == "request"
        else FindingCode.RESPONSE_FIELD_TYPE_CHANGED
    )


def _enum_shrunk_code(side: SchemaSide) -> FindingCode:
    return (
        FindingCode.REQUEST_ENUM_SHRUNK if side == "request" else FindingCode.RESPONSE_ENUM_SHRUNK
    )


def _enum_widened_code(side: SchemaSide) -> FindingCode:
    return (
        FindingCode.REQUEST_ENUM_WIDENED if side == "request" else FindingCode.RESPONSE_ENUM_WIDENED
    )


def _nullable_code(side: SchemaSide) -> FindingCode:
    return (
        FindingCode.REQUEST_NULLABLE_CHANGED
        if side == "request"
        else FindingCode.RESPONSE_NULLABLE_CHANGED
    )


def _read_write_effect_code(side: SchemaSide) -> FindingCode:
    if side == "request":
        return FindingCode.REQUEST_READ_WRITE_EFFECT_CHANGED
    return FindingCode.RESPONSE_READ_WRITE_EFFECT_CHANGED


def _field_added_compatibility(
    side: SchemaSide, is_required_in_new: bool
) -> CompatibilityClassification:
    if side == "request":
        if is_required_in_new:
            return CompatibilityClassification.BREAKING
        return CompatibilityClassification.NON_BREAKING
    return CompatibilityClassification.NON_BREAKING


def _field_removed_compatibility(side: SchemaSide) -> CompatibilityClassification:
    if side == "request":
        return CompatibilityClassification.NON_BREAKING
    return CompatibilityClassification.BREAKING


def _field_type_compatibility(side: SchemaSide) -> CompatibilityClassification:
    if side == "request":
        return CompatibilityClassification.POTENTIALLY_BREAKING
    return CompatibilityClassification.BREAKING


def _nullable_compatibility(
    side: SchemaSide,
    old_nullable: bool,
    new_nullable: bool,
) -> CompatibilityClassification:
    if side == "request":
        if old_nullable is False and new_nullable is True:
            return CompatibilityClassification.NON_BREAKING
        if old_nullable is True and new_nullable is False:
            return CompatibilityClassification.BREAKING
        return CompatibilityClassification.UNKNOWN
    if old_nullable is False and new_nullable is True:
        return CompatibilityClassification.POTENTIALLY_BREAKING
    if old_nullable is True and new_nullable is False:
        return CompatibilityClassification.NON_BREAKING
    return CompatibilityClassification.UNKNOWN


def _read_write_compatibility(
    side: SchemaSide,
    old_visible: bool,
    new_visible: bool,
) -> CompatibilityClassification:
    if side == "request":
        if old_visible and not new_visible:
            return CompatibilityClassification.POTENTIALLY_BREAKING
        return CompatibilityClassification.NON_BREAKING
    if old_visible and not new_visible:
        return CompatibilityClassification.BREAKING
    return CompatibilityClassification.NON_BREAKING


__all__ = [
    "CompatibilityClassification",
    "ConfidenceLevel",
    "DiffEngineError",
    "DiffFinding",
    "FindingCategory",
    "FindingCode",
    "LocationMarker",
    "diff_canonical_snapshots",
]
