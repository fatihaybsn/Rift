"""Additional deterministic diff engine branch coverage tests."""

from __future__ import annotations

import pytest

from app.core.diff_engine import (
    CompatibilityClassification,
    DiffEngineError,
    FindingCode,
    diff_canonical_snapshots,
)
from app.core.openapi_processing import (
    CanonicalOpenAPISnapshot,
    CanonicalOperation,
    CanonicalRequestBody,
    CanonicalResponse,
    CanonicalSchema,
    CanonicalSchemaProperty,
)
from tests.fixtures.diff_snapshots import (
    build_operation_surface_snapshots,
    build_parameter_change_snapshots,
    build_request_change_snapshots,
    build_response_change_snapshots,
)


def _find_one(findings, code: FindingCode):
    matches = [item for item in findings if item.code == code]
    assert matches, f"expected finding code {code.value}"
    return matches[0]


def test_parameter_location_pairing_skips_ambiguous_name_transitions() -> None:
    old_snapshot, new_snapshot = build_parameter_change_snapshots()
    old_operation = old_snapshot.operations[0]
    new_operation = new_snapshot.operations[0]

    old_status = next(item for item in old_operation.parameters if item.name == "status")
    new_status = next(item for item in new_operation.parameters if item.name == "status")

    old_limit = next(item for item in old_operation.parameters if item.name == "limit")
    new_limit = next(item for item in new_operation.parameters if item.name == "limit")

    extra_status = type(new_status)(
        name="status",
        location="cookie",
        origin=new_status.origin,
        required=False,
        schema=new_status.schema,
    )
    extra_limit = type(new_limit)(
        name="limit",
        location="cookie",
        origin=new_limit.origin,
        required=False,
        schema=new_limit.schema,
    )

    mutated_old = CanonicalOpenAPISnapshot(
        schema_version=old_snapshot.schema_version,
        openapi_version=old_snapshot.openapi_version,
        top_level_security=old_snapshot.top_level_security,
        security_schemes=old_snapshot.security_schemes,
        operations=(
            CanonicalOperation(
                path=old_operation.path,
                method=old_operation.method,
                operation_id=old_operation.operation_id,
                deprecated=old_operation.deprecated,
                parameters=(
                    *(
                        item
                        for item in old_operation.parameters
                        if item.name not in {"status", "limit"}
                    ),
                    old_status,
                    old_limit,
                ),
                request_body=old_operation.request_body,
                responses=old_operation.responses,
                security_override=old_operation.security_override,
            ),
        ),
    )
    mutated_new = CanonicalOpenAPISnapshot(
        schema_version=new_snapshot.schema_version,
        openapi_version=new_snapshot.openapi_version,
        top_level_security=new_snapshot.top_level_security,
        security_schemes=new_snapshot.security_schemes,
        operations=(
            CanonicalOperation(
                path=new_operation.path,
                method=new_operation.method,
                operation_id=new_operation.operation_id,
                deprecated=new_operation.deprecated,
                parameters=(
                    *(
                        item
                        for item in new_operation.parameters
                        if item.name not in {"status", "limit"}
                    ),
                    new_status,
                    extra_status,
                    new_limit,
                    extra_limit,
                ),
                request_body=new_operation.request_body,
                responses=new_operation.responses,
                security_override=new_operation.security_override,
            ),
        ),
    )

    findings = diff_canonical_snapshots(mutated_old, mutated_new)
    codes = {item.code for item in findings}
    assert FindingCode.PARAMETER_LOCATION_CHANGED not in codes
    assert FindingCode.PARAMETER_REMOVED in codes
    assert FindingCode.PARAMETER_ADDED in codes


def test_diff_skips_non_subset_enum_changes() -> None:
    old_snapshot, _ = build_request_change_snapshots()
    operation = old_snapshot.operations[0]
    media = operation.request_body.media_types[0]
    schema = media.schema

    role_old = next(item for item in schema.properties if item.name == "role")
    mutated_old_role = CanonicalSchema(
        type=role_old.schema.type,
        format=role_old.schema.format,
        enum=("a", "b"),
        nullable=role_old.schema.nullable,
        required=role_old.schema.required,
        properties=role_old.schema.properties,
        items=role_old.schema.items,
        additional_properties=role_old.schema.additional_properties,
        read_only=role_old.schema.read_only,
        write_only=role_old.schema.write_only,
        deprecated=role_old.schema.deprecated,
        all_of=role_old.schema.all_of,
        one_of=role_old.schema.one_of,
        any_of=role_old.schema.any_of,
        discriminator=role_old.schema.discriminator,
    )
    mutated_new_role = CanonicalSchema(
        type=role_old.schema.type,
        format=role_old.schema.format,
        enum=("a", "c"),
        nullable=role_old.schema.nullable,
        required=role_old.schema.required,
        properties=role_old.schema.properties,
        items=role_old.schema.items,
        additional_properties=role_old.schema.additional_properties,
        read_only=role_old.schema.read_only,
        write_only=role_old.schema.write_only,
        deprecated=role_old.schema.deprecated,
        all_of=role_old.schema.all_of,
        one_of=role_old.schema.one_of,
        any_of=role_old.schema.any_of,
        discriminator=role_old.schema.discriminator,
    )

    def _replace_role(target: CanonicalSchema, replacement: CanonicalSchema) -> CanonicalSchema:
        return CanonicalSchema(
            type=target.type,
            format=target.format,
            enum=target.enum,
            nullable=target.nullable,
            required=target.required,
            properties=tuple(
                CanonicalSchemaProperty(
                    name=item.name,
                    schema=replacement if item.name == "role" else item.schema,
                )
                for item in target.properties
            ),
            items=target.items,
            additional_properties=target.additional_properties,
            read_only=target.read_only,
            write_only=target.write_only,
            deprecated=target.deprecated,
            all_of=target.all_of,
            one_of=target.one_of,
            any_of=target.any_of,
            discriminator=target.discriminator,
        )

    mutated_old_media = type(media)(
        media_type=media.media_type,
        schema=_replace_role(schema, mutated_old_role),
    )
    mutated_new_media = type(media)(
        media_type=media.media_type,
        schema=_replace_role(schema, mutated_new_role),
    )

    mutated_old = CanonicalOpenAPISnapshot(
        schema_version=old_snapshot.schema_version,
        openapi_version=old_snapshot.openapi_version,
        top_level_security=old_snapshot.top_level_security,
        security_schemes=old_snapshot.security_schemes,
        operations=(
            CanonicalOperation(
                path=operation.path,
                method=operation.method,
                operation_id=operation.operation_id,
                deprecated=operation.deprecated,
                parameters=operation.parameters,
                request_body=CanonicalRequestBody(
                    present=True,
                    required=operation.request_body.required,
                    media_types=(mutated_old_media,),
                ),
                responses=operation.responses,
                security_override=operation.security_override,
            ),
        ),
    )
    mutated_new = CanonicalOpenAPISnapshot(
        schema_version=old_snapshot.schema_version,
        openapi_version=old_snapshot.openapi_version,
        top_level_security=old_snapshot.top_level_security,
        security_schemes=old_snapshot.security_schemes,
        operations=(
            CanonicalOperation(
                path=operation.path,
                method=operation.method,
                operation_id=operation.operation_id,
                deprecated=operation.deprecated,
                parameters=operation.parameters,
                request_body=CanonicalRequestBody(
                    present=True,
                    required=operation.request_body.required,
                    media_types=(mutated_new_media,),
                ),
                responses=operation.responses,
                security_override=operation.security_override,
            ),
        ),
    )

    findings = diff_canonical_snapshots(mutated_old, mutated_new)
    codes = {item.code for item in findings}
    assert FindingCode.REQUEST_ENUM_SHRUNK not in codes
    assert FindingCode.REQUEST_ENUM_WIDENED not in codes


def test_diff_detects_nested_items_schema_changes() -> None:
    old_snapshot = build_request_change_snapshots()[0]
    operation = old_snapshot.operations[0]
    media = operation.request_body.media_types[0]
    array_schema = CanonicalSchema(
        type="array",
        format=None,
        enum=None,
        nullable=False,
        required=(),
        properties=(),
        items=CanonicalSchema(
            type="string",
            format=None,
            enum=None,
            nullable=False,
            required=(),
            properties=(),
            items=None,
            additional_properties=True,
            read_only=False,
            write_only=False,
            deprecated=False,
            all_of=(),
            one_of=(),
            any_of=(),
            discriminator=None,
        ),
        additional_properties=True,
        read_only=False,
        write_only=False,
        deprecated=False,
        all_of=(),
        one_of=(),
        any_of=(),
        discriminator=None,
    )
    array_schema_changed = CanonicalSchema(
        type="array",
        format=None,
        enum=None,
        nullable=False,
        required=(),
        properties=(),
        items=CanonicalSchema(
            type="integer",
            format=None,
            enum=None,
            nullable=False,
            required=(),
            properties=(),
            items=None,
            additional_properties=True,
            read_only=False,
            write_only=False,
            deprecated=False,
            all_of=(),
            one_of=(),
            any_of=(),
            discriminator=None,
        ),
        additional_properties=True,
        read_only=False,
        write_only=False,
        deprecated=False,
        all_of=(),
        one_of=(),
        any_of=(),
        discriminator=None,
    )

    def _with_tags(root: CanonicalSchema, tags_schema: CanonicalSchema) -> CanonicalSchema:
        return CanonicalSchema(
            type=root.type,
            format=root.format,
            enum=root.enum,
            nullable=root.nullable,
            required=root.required,
            properties=tuple(
                (*root.properties, CanonicalSchemaProperty(name="tags", schema=tags_schema))
            ),
            items=root.items,
            additional_properties=root.additional_properties,
            read_only=root.read_only,
            write_only=root.write_only,
            deprecated=root.deprecated,
            all_of=root.all_of,
            one_of=root.one_of,
            any_of=root.any_of,
            discriminator=root.discriminator,
        )

    old_with_tags = type(media)(
        media_type=media.media_type,
        schema=_with_tags(media.schema, array_schema),
    )
    new_with_tags = type(media)(
        media_type=media.media_type,
        schema=_with_tags(media.schema, array_schema_changed),
    )

    mutated_old = CanonicalOpenAPISnapshot(
        schema_version=old_snapshot.schema_version,
        openapi_version=old_snapshot.openapi_version,
        top_level_security=old_snapshot.top_level_security,
        security_schemes=old_snapshot.security_schemes,
        operations=(
            CanonicalOperation(
                path=operation.path,
                method=operation.method,
                operation_id=operation.operation_id,
                deprecated=operation.deprecated,
                parameters=operation.parameters,
                request_body=CanonicalRequestBody(
                    present=True,
                    required=operation.request_body.required,
                    media_types=(old_with_tags,),
                ),
                responses=operation.responses,
                security_override=operation.security_override,
            ),
        ),
    )
    mutated_new = CanonicalOpenAPISnapshot(
        schema_version=old_snapshot.schema_version,
        openapi_version=old_snapshot.openapi_version,
        top_level_security=old_snapshot.top_level_security,
        security_schemes=old_snapshot.security_schemes,
        operations=(
            CanonicalOperation(
                path=operation.path,
                method=operation.method,
                operation_id=operation.operation_id,
                deprecated=operation.deprecated,
                parameters=operation.parameters,
                request_body=CanonicalRequestBody(
                    present=True,
                    required=operation.request_body.required,
                    media_types=(new_with_tags,),
                ),
                responses=operation.responses,
                security_override=operation.security_override,
            ),
        ),
    )

    finding = _find_one(
        diff_canonical_snapshots(mutated_old, mutated_new),
        FindingCode.REQUEST_FIELD_TYPE_CHANGED,
    )
    assert finding.field_path == "/properties/tags/items"


def test_diff_skips_hidden_property_add_remove_by_directionality() -> None:
    old_snapshot = build_request_change_snapshots()[0]
    operation = old_snapshot.operations[0]
    schema = operation.request_body.media_types[0].schema
    hidden_added = CanonicalSchemaProperty(
        name="serverOnly",
        schema=CanonicalSchema(
            type="string",
            format=None,
            enum=None,
            nullable=False,
            required=(),
            properties=(),
            items=None,
            additional_properties=True,
            read_only=True,
            write_only=False,
            deprecated=False,
            all_of=(),
            one_of=(),
            any_of=(),
            discriminator=None,
        ),
    )
    with_hidden_schema = CanonicalSchema(
        type=schema.type,
        format=schema.format,
        enum=schema.enum,
        nullable=schema.nullable,
        required=schema.required,
        properties=(*schema.properties, hidden_added),
        items=schema.items,
        additional_properties=schema.additional_properties,
        read_only=schema.read_only,
        write_only=schema.write_only,
        deprecated=schema.deprecated,
        all_of=schema.all_of,
        one_of=schema.one_of,
        any_of=schema.any_of,
        discriminator=schema.discriminator,
    )
    without_hidden_media = type(operation.request_body.media_types[0])(
        media_type=operation.request_body.media_types[0].media_type,
        schema=schema,
    )
    with_hidden_media = type(operation.request_body.media_types[0])(
        media_type=operation.request_body.media_types[0].media_type,
        schema=with_hidden_schema,
    )
    old_with_hidden = CanonicalOpenAPISnapshot(
        schema_version=old_snapshot.schema_version,
        openapi_version=old_snapshot.openapi_version,
        top_level_security=old_snapshot.top_level_security,
        security_schemes=old_snapshot.security_schemes,
        operations=(
            CanonicalOperation(
                path=operation.path,
                method=operation.method,
                operation_id=operation.operation_id,
                deprecated=operation.deprecated,
                parameters=operation.parameters,
                request_body=CanonicalRequestBody(
                    present=True,
                    required=operation.request_body.required,
                    media_types=(with_hidden_media,),
                ),
                responses=operation.responses,
                security_override=operation.security_override,
            ),
        ),
    )
    new_without_hidden = CanonicalOpenAPISnapshot(
        schema_version=old_snapshot.schema_version,
        openapi_version=old_snapshot.openapi_version,
        top_level_security=old_snapshot.top_level_security,
        security_schemes=old_snapshot.security_schemes,
        operations=(
            CanonicalOperation(
                path=operation.path,
                method=operation.method,
                operation_id=operation.operation_id,
                deprecated=operation.deprecated,
                parameters=operation.parameters,
                request_body=CanonicalRequestBody(
                    present=True,
                    required=operation.request_body.required,
                    media_types=(without_hidden_media,),
                ),
                responses=operation.responses,
                security_override=operation.security_override,
            ),
        ),
    )
    findings = diff_canonical_snapshots(old_with_hidden, new_without_hidden)
    assert FindingCode.REQUEST_FIELD_REMOVED not in {item.code for item in findings}


def test_diff_rejects_invalid_snapshot_type() -> None:
    _, new_snapshot = build_operation_surface_snapshots()
    with pytest.raises(DiffEngineError, match="snapshot type is invalid"):
        diff_canonical_snapshots("bad", new_snapshot)  # type: ignore[arg-type]


def test_diff_validation_rejects_invalid_method_enum() -> None:
    old_snapshot, new_snapshot = build_operation_surface_snapshots()
    operation = old_snapshot.operations[0]
    mutated_old = CanonicalOpenAPISnapshot(
        schema_version=old_snapshot.schema_version,
        openapi_version=old_snapshot.openapi_version,
        top_level_security=old_snapshot.top_level_security,
        security_schemes=old_snapshot.security_schemes,
        operations=(
            CanonicalOperation(
                path=operation.path,
                method="fetch",  # type: ignore[arg-type]
                operation_id=operation.operation_id,
                deprecated=operation.deprecated,
                parameters=operation.parameters,
                request_body=operation.request_body,
                responses=operation.responses,
                security_override=operation.security_override,
            ),
        ),
    )
    with pytest.raises(DiffEngineError, match="method 'fetch' is not supported"):
        diff_canonical_snapshots(mutated_old, new_snapshot)


def test_diff_validation_rejects_invalid_schema_shape_variants() -> None:
    old_snapshot, new_snapshot = build_response_change_snapshots()
    operation = old_snapshot.operations[0]
    response_media = operation.responses[0].media_types[0]

    for kwargs, expected in (
        ({"enum": ["a"]}, "schema.enum must be tuple/null"),
        ({"required": ["a"]}, "schema.required must be tuple"),
        ({"properties": []}, "schema.properties must be tuple"),
        ({"additional_properties": "x"}, "schema.additional_properties must be boolean or schema"),
        ({"items": "x"}, "schema.items must be null or schema"),
        ({"all_of": []}, "schema.all_of must be tuple"),
        ({"one_of": []}, "schema.one_of must be tuple"),
        ({"any_of": []}, "schema.any_of must be tuple"),
    ):
        base = {
            "type": response_media.schema.type,
            "format": response_media.schema.format,
            "enum": response_media.schema.enum,
            "nullable": response_media.schema.nullable,
            "required": response_media.schema.required,
            "properties": response_media.schema.properties,
            "items": response_media.schema.items,
            "additional_properties": response_media.schema.additional_properties,
            "read_only": response_media.schema.read_only,
            "write_only": response_media.schema.write_only,
            "deprecated": response_media.schema.deprecated,
            "all_of": response_media.schema.all_of,
            "one_of": response_media.schema.one_of,
            "any_of": response_media.schema.any_of,
            "discriminator": response_media.schema.discriminator,
        }
        base.update(kwargs)
        mutated_schema = CanonicalSchema(
            **base,  # type: ignore[arg-type]
        )
        mutated_media = type(response_media)(
            media_type=response_media.media_type,
            schema=mutated_schema,
        )
        mutated_response = CanonicalResponse(
            status_code=operation.responses[0].status_code,
            media_types=(mutated_media,),
        )
        mutated_old = CanonicalOpenAPISnapshot(
            schema_version=old_snapshot.schema_version,
            openapi_version=old_snapshot.openapi_version,
            top_level_security=old_snapshot.top_level_security,
            security_schemes=old_snapshot.security_schemes,
            operations=(
                CanonicalOperation(
                    path=operation.path,
                    method=operation.method,
                    operation_id=operation.operation_id,
                    deprecated=operation.deprecated,
                    parameters=operation.parameters,
                    request_body=operation.request_body,
                    responses=(mutated_response,),
                    security_override=operation.security_override,
                ),
            ),
        )
        with pytest.raises(DiffEngineError, match=expected):
            diff_canonical_snapshots(mutated_old, new_snapshot)


def test_diff_status_sort_fallback_and_unknown_nullable_compatibility_branch() -> None:
    old_snapshot, new_snapshot = build_request_change_snapshots()
    old_operation = old_snapshot.operations[0]
    new_operation = new_snapshot.operations[0]
    old_media = old_operation.request_body.media_types[0]
    new_media = new_operation.request_body.media_types[0]

    old_nullable_unknown = CanonicalSchema(
        type=old_media.schema.type,
        format=old_media.schema.format,
        enum=old_media.schema.enum,
        nullable=old_media.schema.nullable,
        required=old_media.schema.required,
        properties=old_media.schema.properties,
        items=old_media.schema.items,
        additional_properties=old_media.schema.additional_properties,
        read_only=old_media.schema.read_only,
        write_only=old_media.schema.write_only,
        deprecated=old_media.schema.deprecated,
        all_of=old_media.schema.all_of,
        one_of=old_media.schema.one_of,
        any_of=old_media.schema.any_of,
        discriminator=old_media.schema.discriminator,
    )
    new_nullable_unknown = CanonicalSchema(
        type=new_media.schema.type,
        format=new_media.schema.format,
        enum=new_media.schema.enum,
        nullable=new_media.schema.nullable,
        required=new_media.schema.required,
        properties=new_media.schema.properties,
        items=new_media.schema.items,
        additional_properties=new_media.schema.additional_properties,
        read_only=new_media.schema.read_only,
        write_only=new_media.schema.write_only,
        deprecated=new_media.schema.deprecated,
        all_of=new_media.schema.all_of,
        one_of=new_media.schema.one_of,
        any_of=new_media.schema.any_of,
        discriminator=new_media.schema.discriminator,
    )
    object.__setattr__(old_nullable_unknown, "nullable", 1)  # type: ignore[arg-type]
    object.__setattr__(new_nullable_unknown, "nullable", 2)  # type: ignore[arg-type]

    mutated_old = CanonicalOpenAPISnapshot(
        schema_version=old_snapshot.schema_version,
        openapi_version=old_snapshot.openapi_version,
        top_level_security=old_snapshot.top_level_security,
        security_schemes=old_snapshot.security_schemes,
        operations=(
            CanonicalOperation(
                path=old_operation.path,
                method=old_operation.method,
                operation_id=old_operation.operation_id,
                deprecated=old_operation.deprecated,
                parameters=old_operation.parameters,
                request_body=CanonicalRequestBody(
                    present=True,
                    required=old_operation.request_body.required,
                    media_types=(
                        type(old_media)(
                            media_type=old_media.media_type,
                            schema=old_nullable_unknown,
                        ),
                    ),
                ),
                responses=(
                    CanonicalResponse(status_code="zzz", media_types=()),
                    *old_operation.responses,
                ),
                security_override=old_operation.security_override,
            ),
        ),
    )
    mutated_new = CanonicalOpenAPISnapshot(
        schema_version=new_snapshot.schema_version,
        openapi_version=new_snapshot.openapi_version,
        top_level_security=new_snapshot.top_level_security,
        security_schemes=new_snapshot.security_schemes,
        operations=(
            CanonicalOperation(
                path=new_operation.path,
                method=new_operation.method,
                operation_id=new_operation.operation_id,
                deprecated=new_operation.deprecated,
                parameters=new_operation.parameters,
                request_body=CanonicalRequestBody(
                    present=True,
                    required=new_operation.request_body.required,
                    media_types=(
                        type(new_media)(
                            media_type=new_media.media_type,
                            schema=new_nullable_unknown,
                        ),
                    ),
                ),
                responses=(
                    CanonicalResponse(status_code="abc", media_types=()),
                    *new_operation.responses,
                ),
                security_override=new_operation.security_override,
            ),
        ),
    )

    with pytest.raises(DiffEngineError, match="schema.nullable must be boolean"):
        diff_canonical_snapshots(mutated_old, mutated_new)


def test_request_read_write_visibility_change_old_hidden_new_visible_is_non_breaking() -> None:
    old_snapshot, new_snapshot = build_request_change_snapshots()
    finding = _find_one(
        diff_canonical_snapshots(old_snapshot, new_snapshot),
        FindingCode.REQUEST_READ_WRITE_EFFECT_CHANGED,
    )
    assert finding.compatibility is CompatibilityClassification.NON_BREAKING
