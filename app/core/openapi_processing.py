"""OpenAPI parsing, validation, and deterministic canonical normalization."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Final, Literal

import yaml
from openapi_spec_validator import validate
from openapi_spec_validator.validation.exceptions import (
    OpenAPISpecValidatorError,
    OpenAPIValidationError,
)
from referencing.exceptions import (
    NoSuchAnchor,
    NoSuchResource,
    PointerToNowhere,
    Unresolvable,
)

HTTP_METHODS: Final[tuple[str, ...]] = (
    "delete",
    "get",
    "head",
    "options",
    "patch",
    "post",
    "put",
    "trace",
)
PARAMETER_LOCATIONS: Final[set[str]] = {"query", "header", "path", "cookie"}
SUPPORTED_MAJOR_MINOR_VERSIONS: Final[set[tuple[int, int]]] = {(3, 0), (3, 1)}
RESPONSE_CODE_PATTERN = re.compile(r"^(?:default|[1-5][0-9][0-9]|[1-5]XX)$")
DEFERRED_SCHEMA_KEYWORDS: Final[set[str]] = {
    "not",
    "if",
    "then",
    "else",
    "dependentSchemas",
    "unevaluatedProperties",
    "unevaluatedItems",
    "patternProperties",
}

ParameterOrigin = Literal["path_item", "operation"]

# Explicit MVP normalization decisions:
# - `servers` is intentionally excluded from canonical output because run-level
#   network target metadata is not part of deterministic API-contract diff identity.
# - Parameter serialization keys (`style`, `explode`) are intentionally deferred.
#   We fail loudly if they are set to non-default values to avoid silent semantic loss.
DEFAULT_PARAMETER_STYLE_BY_LOCATION: Final[dict[str, str]] = {
    "query": "form",
    "cookie": "form",
    "path": "simple",
    "header": "simple",
}
DEFAULT_EXPLODE_BY_STYLE: Final[dict[str, bool]] = {
    "form": True,
    "simple": False,
    "matrix": False,
    "label": False,
    "spaceDelimited": False,
    "pipeDelimited": False,
    "deepObject": True,
}


class OpenAPIProcessingError(ValueError):
    """Raised when parsing, validating, or normalizing OpenAPI content fails."""


@dataclass(frozen=True)
class CanonicalDiscriminator:
    """Deterministic discriminator representation."""

    property_name: str
    mapping: tuple[tuple[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "property_name": self.property_name,
            "mapping": [{"value": key, "ref": ref_value} for key, ref_value in self.mapping],
        }


@dataclass(frozen=True)
class CanonicalSchemaProperty:
    """Named object property in canonical schema form."""

    name: str
    schema: CanonicalSchema

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "schema": self.schema.to_dict()}


@dataclass(frozen=True)
class CanonicalSchema:
    """Canonical subset of schema semantics needed by deterministic diffing."""

    type: str | None
    format: str | None
    enum: tuple[Any, ...] | None
    nullable: bool
    required: tuple[str, ...]
    properties: tuple[CanonicalSchemaProperty, ...]
    items: CanonicalSchema | None
    additional_properties: bool | CanonicalSchema
    read_only: bool
    write_only: bool
    deprecated: bool
    all_of: tuple[CanonicalSchema, ...]
    one_of: tuple[CanonicalSchema, ...]
    any_of: tuple[CanonicalSchema, ...]
    discriminator: CanonicalDiscriminator | None

    def to_dict(self) -> dict[str, Any]:
        additional_properties_payload: bool | dict[str, Any]
        if isinstance(self.additional_properties, bool):
            additional_properties_payload = self.additional_properties
        else:
            additional_properties_payload = self.additional_properties.to_dict()

        return {
            "type": self.type,
            "format": self.format,
            "enum": list(self.enum) if self.enum is not None else None,
            "nullable": self.nullable,
            "required": list(self.required),
            "properties": [item.to_dict() for item in self.properties],
            "items": self.items.to_dict() if self.items is not None else None,
            "additional_properties": additional_properties_payload,
            "read_only": self.read_only,
            "write_only": self.write_only,
            "deprecated": self.deprecated,
            "all_of": [item.to_dict() for item in self.all_of],
            "one_of": [item.to_dict() for item in self.one_of],
            "any_of": [item.to_dict() for item in self.any_of],
            "discriminator": self.discriminator.to_dict()
            if self.discriminator is not None
            else None,
        }


@dataclass(frozen=True)
class CanonicalMediaTypeSchema:
    """Schema bound to a concrete media type."""

    media_type: str
    schema: CanonicalSchema

    def to_dict(self) -> dict[str, Any]:
        return {"media_type": self.media_type, "schema": self.schema.to_dict()}


@dataclass(frozen=True)
class CanonicalParameter:
    """Canonical operation parameter."""

    name: str
    location: str
    origin: ParameterOrigin
    required: bool
    schema: CanonicalSchema

    @property
    def identity(self) -> tuple[str, str]:
        return (self.name, self.location)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "in": self.location,
            "origin": self.origin,
            "required": self.required,
            "schema": self.schema.to_dict(),
        }


@dataclass(frozen=True)
class CanonicalRequestBody:
    """Canonical request-body representation."""

    present: bool
    required: bool
    media_types: tuple[CanonicalMediaTypeSchema, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "present": self.present,
            "required": self.required,
            "content": [item.to_dict() for item in self.media_types],
        }


@dataclass(frozen=True)
class CanonicalResponse:
    """Canonical response representation."""

    status_code: str
    media_types: tuple[CanonicalMediaTypeSchema, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status_code": self.status_code,
            "content": [item.to_dict() for item in self.media_types],
        }


@dataclass(frozen=True)
class CanonicalSecurityRequirementEntry:
    """Single security scheme and scope set inside one requirement object."""

    scheme: str
    scopes: tuple[str, ...]

    def to_pair(self) -> tuple[str, list[str]]:
        return (self.scheme, list(self.scopes))


@dataclass(frozen=True)
class CanonicalSecurityRequirement:
    """One OpenAPI security requirement object."""

    entries: tuple[CanonicalSecurityRequirementEntry, ...]

    def to_dict(self) -> dict[str, list[str]]:
        return dict(entry.to_pair() for entry in self.entries)


@dataclass(frozen=True)
class CanonicalOAuthFlow:
    """Canonical OAuth flow subset needed for diffing."""

    flow: str
    authorization_url: str | None
    token_url: str | None
    refresh_url: str | None
    scopes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "flow": self.flow,
            "authorization_url": self.authorization_url,
            "token_url": self.token_url,
            "refresh_url": self.refresh_url,
            "scopes": list(self.scopes),
        }


@dataclass(frozen=True)
class CanonicalSecurityScheme:
    """Canonical security scheme definition."""

    name: str
    type: str
    scheme: str | None
    bearer_format: str | None
    api_key_name: str | None
    api_key_in: str | None
    open_id_connect_url: str | None
    oauth_flows: tuple[CanonicalOAuthFlow, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "scheme": self.scheme,
            "bearer_format": self.bearer_format,
            "api_key_name": self.api_key_name,
            "api_key_in": self.api_key_in,
            "open_id_connect_url": self.open_id_connect_url,
            "oauth_flows": [flow.to_dict() for flow in self.oauth_flows],
        }


@dataclass(frozen=True)
class CanonicalOperation:
    """Canonical operation representation."""

    path: str
    method: str
    operation_id: str | None
    deprecated: bool
    parameters: tuple[CanonicalParameter, ...]
    request_body: CanonicalRequestBody
    responses: tuple[CanonicalResponse, ...]
    security_override: tuple[CanonicalSecurityRequirement, ...] | None

    def to_dict(self) -> dict[str, Any]:
        security_override_payload: list[dict[str, list[str]]] | None
        if self.security_override is None:
            security_override_payload = None
        else:
            security_override_payload = [
                requirement.to_dict() for requirement in self.security_override
            ]

        return {
            "path": self.path,
            "method": self.method,
            "operation_id": self.operation_id,
            "deprecated": self.deprecated,
            "parameters": [parameter.to_dict() for parameter in self.parameters],
            "request_body": self.request_body.to_dict(),
            "responses": [response.to_dict() for response in self.responses],
            "security_override": security_override_payload,
        }


@dataclass(frozen=True)
class CanonicalOpenAPISnapshot:
    """Canonical normalized OpenAPI snapshot used by later deterministic diffing."""

    schema_version: str
    openapi_version: str
    top_level_security: tuple[CanonicalSecurityRequirement, ...]
    security_schemes: tuple[CanonicalSecurityScheme, ...]
    operations: tuple[CanonicalOperation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "openapi_version": self.openapi_version,
            "security": {
                "top_level_requirements": [
                    requirement.to_dict() for requirement in self.top_level_security
                ],
                "schemes": [scheme.to_dict() for scheme in self.security_schemes],
            },
            "operations": [operation.to_dict() for operation in self.operations],
        }

    def checksum(self) -> str:
        canonical_json = serialize_canonical_json(self.to_dict())
        return sha256(canonical_json.encode("utf-8")).hexdigest()


def parse_openapi_document(raw_bytes: bytes, *, source: str) -> dict[str, Any]:
    """Parse raw JSON or YAML bytes into a mapping."""
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OpenAPIProcessingError(f"{source}: input is not valid UTF-8.") from exc

    stripped = text.lstrip()
    parser_order: tuple[str, str]
    if stripped.startswith("{") or stripped.startswith("["):
        parser_order = ("json", "yaml")
    else:
        parser_order = ("yaml", "json")

    parser_errors: list[str] = []
    parsed: Any | None = None

    for parser_name in parser_order:
        try:
            if parser_name == "json":
                parsed = json.loads(text)
            else:
                parsed = yaml.safe_load(text)
            break
        except (json.JSONDecodeError, yaml.YAMLError, TypeError, ValueError) as exc:
            parser_errors.append(f"{parser_name}: {exc}")

    if parsed is None:
        details = "; ".join(parser_errors)
        raise OpenAPIProcessingError(f"{source}: invalid JSON/YAML input ({details}).")

    if not isinstance(parsed, dict):
        raise OpenAPIProcessingError(f"{source}: top-level document must be a JSON/YAML object.")

    return parsed


def validate_openapi_document(document: Mapping[str, Any], *, source: str) -> str:
    """Validate OpenAPI version support and structural correctness."""
    openapi_version = document.get("openapi")
    if not isinstance(openapi_version, str):
        raise OpenAPIProcessingError(f"{source}: missing or invalid 'openapi' version string.")

    if not _is_supported_openapi_version(openapi_version):
        raise OpenAPIProcessingError(
            f"{source}: unsupported OpenAPI version {openapi_version!r}. "
            "Supported versions are 3.0.x and 3.1.x."
        )

    try:
        validate(document)
    except (OpenAPISpecValidatorError, OpenAPIValidationError, ValueError, TypeError) as exc:
        raise OpenAPIProcessingError(f"{source}: invalid OpenAPI document: {exc}") from exc
    except (PointerToNowhere, Unresolvable, NoSuchResource, NoSuchAnchor) as exc:
        raise OpenAPIProcessingError(f"{source}: unresolved $ref: {exc}") from exc

    return openapi_version


def parse_validate_and_normalize_openapi(
    raw_bytes: bytes,
    *,
    source: str,
    schema_version: str = "v1",
) -> CanonicalOpenAPISnapshot:
    """Parse, validate, and normalize OpenAPI bytes into canonical form."""
    document = parse_openapi_document(raw_bytes, source=source)
    openapi_version = validate_openapi_document(document, source=source)
    return normalize_openapi_document(
        document=document,
        openapi_version=openapi_version,
        schema_version=schema_version,
    )


def serialize_canonical_json(value: Mapping[str, Any]) -> str:
    """Serialize canonical payload deterministically."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def normalize_openapi_document(
    *,
    document: Mapping[str, Any],
    openapi_version: str,
    schema_version: str = "v1",
) -> CanonicalOpenAPISnapshot:
    """Convert validated OpenAPI mapping into deterministic canonical representation."""
    resolver = _LocalRefResolver(document=document)
    paths_obj = _require_mapping(document.get("paths"), context="paths")

    top_level_security = _normalize_security_requirements(
        document.get("security"),
        context="security",
        allow_missing=True,
    )
    security_schemes = _normalize_security_schemes(document=document, resolver=resolver)

    operations: list[CanonicalOperation] = []

    for path_key in sorted(paths_obj):
        normalized_path = _normalize_path(path_key)
        path_item = resolver.resolve_mapping(paths_obj[path_key], context=f"paths.{path_key}")
        path_parameters = _normalize_parameters(
            path_item.get("parameters"),
            origin="path_item",
            resolver=resolver,
            context=f"paths.{path_key}.parameters",
        )

        for method in HTTP_METHODS:
            raw_operation = path_item.get(method)
            if raw_operation is None:
                continue

            operation_obj = resolver.resolve_mapping(
                raw_operation,
                context=f"paths.{path_key}.{method}",
            )

            operation_parameters = _normalize_parameters(
                operation_obj.get("parameters"),
                origin="operation",
                resolver=resolver,
                context=f"paths.{path_key}.{method}.parameters",
            )

            merged_parameters = dict(path_parameters)
            merged_parameters.update(operation_parameters)

            operation_id = operation_obj.get("operationId")
            if operation_id is not None and not isinstance(operation_id, str):
                raise OpenAPIProcessingError(
                    f"paths.{path_key}.{method}.operationId must be a string when provided."
                )

            security_override: tuple[CanonicalSecurityRequirement, ...] | None
            if "security" not in operation_obj:
                security_override = None
            else:
                security_override = _normalize_security_requirements(
                    operation_obj.get("security"),
                    context=f"paths.{path_key}.{method}.security",
                    allow_missing=False,
                )

            request_body = _normalize_request_body(
                operation_obj.get("requestBody"),
                resolver=resolver,
                context=f"paths.{path_key}.{method}.requestBody",
            )

            responses = _normalize_responses(
                operation_obj.get("responses"),
                resolver=resolver,
                context=f"paths.{path_key}.{method}.responses",
            )

            parameters_tuple = tuple(
                sorted(merged_parameters.values(), key=lambda parameter: parameter.identity)
            )
            operations.append(
                CanonicalOperation(
                    path=normalized_path,
                    method=method,
                    operation_id=operation_id,
                    deprecated=bool(operation_obj.get("deprecated", False)),
                    parameters=parameters_tuple,
                    request_body=request_body,
                    responses=responses,
                    security_override=security_override,
                )
            )

    operations_tuple = tuple(
        sorted(operations, key=lambda operation: (operation.path, operation.method))
    )
    return CanonicalOpenAPISnapshot(
        schema_version=schema_version,
        openapi_version=openapi_version,
        top_level_security=top_level_security,
        security_schemes=security_schemes,
        operations=operations_tuple,
    )


def _is_supported_openapi_version(openapi_version: str) -> bool:
    parts = openapi_version.split(".")
    if len(parts) < 2:
        return False

    try:
        major = int(parts[0])
        minor = int(parts[1])
    except ValueError:
        return False

    return (major, minor) in SUPPORTED_MAJOR_MINOR_VERSIONS


def _normalize_path(path_key: object) -> str:
    if not isinstance(path_key, str):
        raise OpenAPIProcessingError("Path keys must be strings.")

    normalized_path = path_key.strip()
    if not normalized_path.startswith("/"):
        raise OpenAPIProcessingError(f"Invalid path key {path_key!r}; expected leading '/'.")
    return normalized_path


def _require_mapping(value: object, *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OpenAPIProcessingError(f"{context} must be an object.")
    return value


def _require_sequence(value: object, *, context: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise OpenAPIProcessingError(f"{context} must be an array.")
    return value


def _normalize_parameters(
    raw_parameters: object,
    *,
    origin: ParameterOrigin,
    resolver: _LocalRefResolver,
    context: str,
) -> dict[tuple[str, str], CanonicalParameter]:
    if raw_parameters is None:
        return {}

    parameter_items = _require_sequence(raw_parameters, context=context)
    normalized: dict[tuple[str, str], CanonicalParameter] = {}

    for index, raw_parameter in enumerate(parameter_items):
        parameter_obj = resolver.resolve_mapping(raw_parameter, context=f"{context}[{index}]")

        name = parameter_obj.get("name")
        if not isinstance(name, str) or not name:
            raise OpenAPIProcessingError(f"{context}[{index}].name must be a non-empty string.")

        location = parameter_obj.get("in")
        if not isinstance(location, str) or location not in PARAMETER_LOCATIONS:
            raise OpenAPIProcessingError(
                f"{context}[{index}].in must be one of {sorted(PARAMETER_LOCATIONS)}."
            )

        required = bool(parameter_obj.get("required", False))
        if location == "path" and required is not True:
            raise OpenAPIProcessingError(
                f"{context}[{index}] path parameters must declare required=true."
            )

        has_schema = "schema" in parameter_obj
        has_content = "content" in parameter_obj
        if has_schema and has_content:
            raise OpenAPIProcessingError(
                f"{context}[{index}] cannot contain both 'schema' and 'content'."
            )
        if not has_schema and not has_content:
            raise OpenAPIProcessingError(
                f"{context}[{index}] must include either 'schema' or 'content'."
            )

        if has_schema:
            schema = _normalize_schema(
                parameter_obj["schema"],
                resolver=resolver,
                context=f"{context}[{index}].schema",
            )
        else:
            content_obj = _require_mapping(
                parameter_obj["content"], context=f"{context}[{index}].content"
            )
            if len(content_obj) != 1:
                raise OpenAPIProcessingError(
                    f"{context}[{index}].content supports exactly one media type in MVP."
                )
            media_type = sorted(content_obj)[0]
            media_type_obj = _require_mapping(
                content_obj[media_type],
                context=f"{context}[{index}].content.{media_type}",
            )
            if "schema" not in media_type_obj:
                raise OpenAPIProcessingError(
                    f"{context}[{index}].content.{media_type} must include schema."
                )
            schema = _normalize_schema(
                media_type_obj["schema"],
                resolver=resolver,
                context=f"{context}[{index}].content.{media_type}.schema",
            )

        _validate_deferred_parameter_serialization(
            parameter_obj,
            location=location,
            context=f"{context}[{index}]",
        )

        parameter = CanonicalParameter(
            name=name,
            location=location,
            origin=origin,
            required=required,
            schema=schema,
        )

        identity = parameter.identity
        if identity in normalized:
            raise OpenAPIProcessingError(
                f"{context}: duplicate parameter identity (name, in) for {identity!r}."
            )
        normalized[identity] = parameter

    return normalized


def _normalize_request_body(
    raw_request_body: object,
    *,
    resolver: _LocalRefResolver,
    context: str,
) -> CanonicalRequestBody:
    if raw_request_body is None:
        return CanonicalRequestBody(present=False, required=False, media_types=())

    request_body_obj = resolver.resolve_mapping(raw_request_body, context=context)
    required = bool(request_body_obj.get("required", False))
    media_types = _normalize_content_map(
        request_body_obj.get("content"),
        resolver=resolver,
        context=f"{context}.content",
    )
    return CanonicalRequestBody(present=True, required=required, media_types=media_types)


def _validate_deferred_parameter_serialization(
    parameter_obj: Mapping[str, Any],
    *,
    location: str,
    context: str,
) -> None:
    style_value = parameter_obj.get("style")
    explode_value = parameter_obj.get("explode")

    default_style = DEFAULT_PARAMETER_STYLE_BY_LOCATION[location]
    if style_value is None:
        effective_style = default_style
    elif isinstance(style_value, str):
        effective_style = style_value
    else:
        raise OpenAPIProcessingError(f"{context}.style must be a string when present.")

    default_explode = DEFAULT_EXPLODE_BY_STYLE.get(effective_style)
    if explode_value is None:
        effective_explode = default_explode
    elif isinstance(explode_value, bool):
        effective_explode = explode_value
    else:
        raise OpenAPIProcessingError(f"{context}.explode must be a boolean when present.")

    if style_value is not None and effective_style != default_style:
        raise OpenAPIProcessingError(
            f"{context}.style={effective_style!r} is intentionally deferred in MVP normalization."
        )
    if default_explode is not None and effective_explode != default_explode:
        raise OpenAPIProcessingError(
            f"{context}.explode={effective_explode!r} is intentionally "
            "deferred in MVP normalization."
        )


def _normalize_responses(
    raw_responses: object,
    *,
    resolver: _LocalRefResolver,
    context: str,
) -> tuple[CanonicalResponse, ...]:
    responses_obj = _require_mapping(raw_responses, context=context)
    normalized: list[CanonicalResponse] = []

    for status_code in sorted(responses_obj, key=_response_sort_key):
        if not RESPONSE_CODE_PATTERN.match(status_code):
            raise OpenAPIProcessingError(
                f"{context}.{status_code} is not a supported response status key."
            )
        response_obj = resolver.resolve_mapping(
            responses_obj[status_code], context=f"{context}.{status_code}"
        )
        if "headers" in response_obj and response_obj["headers"]:
            raise OpenAPIProcessingError(
                f"{context}.{status_code}.headers is intentionally deferred in MVP normalization."
            )
        media_types = _normalize_content_map(
            response_obj.get("content"),
            resolver=resolver,
            context=f"{context}.{status_code}.content",
        )
        normalized.append(CanonicalResponse(status_code=status_code, media_types=media_types))

    return tuple(normalized)


def _response_sort_key(status_code: str) -> tuple[int, int, str]:
    if status_code == "default":
        return (2, 0, status_code)
    if re.match(r"^[1-5]XX$", status_code):
        return (1, int(status_code[0]), status_code)
    if re.match(r"^[1-5][0-9][0-9]$", status_code):
        return (0, int(status_code), status_code)
    return (3, 0, status_code)


def _normalize_content_map(
    raw_content: object,
    *,
    resolver: _LocalRefResolver,
    context: str,
) -> tuple[CanonicalMediaTypeSchema, ...]:
    if raw_content is None:
        return ()

    content_obj = _require_mapping(raw_content, context=context)
    normalized: list[CanonicalMediaTypeSchema] = []

    for media_type in sorted(content_obj):
        media_type_obj = _require_mapping(
            content_obj[media_type], context=f"{context}.{media_type}"
        )
        if "schema" not in media_type_obj:
            raise OpenAPIProcessingError(f"{context}.{media_type} must include schema.")
        schema = _normalize_schema(
            media_type_obj["schema"],
            resolver=resolver,
            context=f"{context}.{media_type}.schema",
        )
        normalized.append(CanonicalMediaTypeSchema(media_type=media_type, schema=schema))

    return tuple(normalized)


def _normalize_security_requirements(
    raw_security: object,
    *,
    context: str,
    allow_missing: bool,
) -> tuple[CanonicalSecurityRequirement, ...]:
    if raw_security is None:
        if allow_missing:
            return ()
        raise OpenAPIProcessingError(f"{context} must be an array.")

    security_items = _require_sequence(raw_security, context=context)
    normalized: list[CanonicalSecurityRequirement] = []

    for index, raw_requirement in enumerate(security_items):
        requirement_obj = _require_mapping(raw_requirement, context=f"{context}[{index}]")
        entries: list[CanonicalSecurityRequirementEntry] = []
        for scheme_name in sorted(requirement_obj):
            scopes_raw = requirement_obj[scheme_name]
            scopes_list = _require_sequence(scopes_raw, context=f"{context}[{index}].{scheme_name}")
            scopes: list[str] = []
            for scope_index, scope in enumerate(scopes_list):
                if not isinstance(scope, str):
                    raise OpenAPIProcessingError(
                        f"{context}[{index}].{scheme_name}[{scope_index}] must be a string."
                    )
                scopes.append(scope)
            entries.append(
                CanonicalSecurityRequirementEntry(
                    scheme=scheme_name,
                    scopes=tuple(sorted(set(scopes))),
                )
            )
        normalized.append(CanonicalSecurityRequirement(entries=tuple(entries)))

    normalized.sort(
        key=lambda requirement: serialize_canonical_json(requirement.to_dict()),
    )
    return tuple(normalized)


def _normalize_security_schemes(
    *,
    document: Mapping[str, Any],
    resolver: _LocalRefResolver,
) -> tuple[CanonicalSecurityScheme, ...]:
    components_obj = document.get("components")
    if components_obj is None:
        return ()

    components_map = _require_mapping(components_obj, context="components")
    raw_security_schemes = components_map.get("securitySchemes")
    if raw_security_schemes is None:
        return ()

    security_schemes_map = _require_mapping(
        raw_security_schemes, context="components.securitySchemes"
    )
    normalized: list[CanonicalSecurityScheme] = []

    for scheme_name in sorted(security_schemes_map):
        scheme_obj = resolver.resolve_mapping(
            security_schemes_map[scheme_name],
            context=f"components.securitySchemes.{scheme_name}",
        )
        normalized.append(
            _normalize_security_scheme(
                scheme_name=scheme_name,
                scheme_obj=scheme_obj,
                context=f"components.securitySchemes.{scheme_name}",
            )
        )

    return tuple(normalized)


def _normalize_security_scheme(
    *,
    scheme_name: str,
    scheme_obj: Mapping[str, Any],
    context: str,
) -> CanonicalSecurityScheme:
    scheme_type = scheme_obj.get("type")
    if not isinstance(scheme_type, str):
        raise OpenAPIProcessingError(f"{context}.type must be a string.")

    normalized_type = scheme_type
    if normalized_type not in {"apiKey", "http", "oauth2", "openIdConnect", "mutualTLS"}:
        raise OpenAPIProcessingError(f"{context}.type {normalized_type!r} is not supported.")

    scheme = scheme_obj.get("scheme")
    bearer_format = scheme_obj.get("bearerFormat")
    api_key_name = scheme_obj.get("name")
    api_key_in = scheme_obj.get("in")
    open_id_connect_url = scheme_obj.get("openIdConnectUrl")

    if scheme is not None and not isinstance(scheme, str):
        raise OpenAPIProcessingError(f"{context}.scheme must be a string when present.")
    if bearer_format is not None and not isinstance(bearer_format, str):
        raise OpenAPIProcessingError(f"{context}.bearerFormat must be a string when present.")
    if api_key_name is not None and not isinstance(api_key_name, str):
        raise OpenAPIProcessingError(f"{context}.name must be a string when present.")
    if api_key_in is not None and not isinstance(api_key_in, str):
        raise OpenAPIProcessingError(f"{context}.in must be a string when present.")
    if open_id_connect_url is not None and not isinstance(open_id_connect_url, str):
        raise OpenAPIProcessingError(f"{context}.openIdConnectUrl must be a string when present.")

    oauth_flows: tuple[CanonicalOAuthFlow, ...] = ()
    if normalized_type == "apiKey":
        if api_key_name is None or api_key_in not in {"query", "header", "cookie"}:
            raise OpenAPIProcessingError(f"{context} apiKey scheme requires valid 'name' and 'in'.")
    elif normalized_type == "http":
        if scheme is None:
            raise OpenAPIProcessingError(f"{context} http scheme requires 'scheme'.")
    elif normalized_type == "oauth2":
        flows_obj = _require_mapping(scheme_obj.get("flows"), context=f"{context}.flows")
        oauth_flows = _normalize_oauth_flows(flows_obj, context=f"{context}.flows")
    elif normalized_type == "openIdConnect":
        if open_id_connect_url is None:
            raise OpenAPIProcessingError(
                f"{context} openIdConnect scheme requires openIdConnectUrl."
            )

    return CanonicalSecurityScheme(
        name=scheme_name,
        type=normalized_type,
        scheme=scheme,
        bearer_format=bearer_format,
        api_key_name=api_key_name,
        api_key_in=api_key_in,
        open_id_connect_url=open_id_connect_url,
        oauth_flows=oauth_flows,
    )


def _normalize_oauth_flows(
    flows_obj: Mapping[str, Any],
    *,
    context: str,
) -> tuple[CanonicalOAuthFlow, ...]:
    normalized: list[CanonicalOAuthFlow] = []
    for flow_name in sorted(flows_obj):
        flow_obj = _require_mapping(flows_obj[flow_name], context=f"{context}.{flow_name}")
        scopes_map = _require_mapping(
            flow_obj.get("scopes"), context=f"{context}.{flow_name}.scopes"
        )
        scopes = tuple(sorted(str(scope_name) for scope_name in scopes_map))
        authorization_url = flow_obj.get("authorizationUrl")
        token_url = flow_obj.get("tokenUrl")
        refresh_url = flow_obj.get("refreshUrl")

        if authorization_url is not None and not isinstance(authorization_url, str):
            raise OpenAPIProcessingError(
                f"{context}.{flow_name}.authorizationUrl must be a string when present."
            )
        if token_url is not None and not isinstance(token_url, str):
            raise OpenAPIProcessingError(
                f"{context}.{flow_name}.tokenUrl must be a string when present."
            )
        if refresh_url is not None and not isinstance(refresh_url, str):
            raise OpenAPIProcessingError(
                f"{context}.{flow_name}.refreshUrl must be a string when present."
            )

        normalized.append(
            CanonicalOAuthFlow(
                flow=flow_name,
                authorization_url=authorization_url,
                token_url=token_url,
                refresh_url=refresh_url,
                scopes=scopes,
            )
        )
    return tuple(normalized)


def _normalize_schema(
    raw_schema: object,
    *,
    resolver: _LocalRefResolver,
    context: str,
) -> CanonicalSchema:
    schema_obj = resolver.resolve_mapping(raw_schema, context=context)

    deferred_keys = sorted(DEFERRED_SCHEMA_KEYWORDS.intersection(schema_obj.keys()))
    if deferred_keys:
        raise OpenAPIProcessingError(
            f"{context}: schema keywords {deferred_keys} are intentionally deferred in MVP."
        )

    nullable = bool(schema_obj.get("nullable", False))
    raw_type = schema_obj.get("type")
    normalized_type: str | None = None
    if raw_type is None:
        normalized_type = None
    elif isinstance(raw_type, str):
        normalized_type = raw_type
    elif isinstance(raw_type, list):
        type_values = [item for item in raw_type if isinstance(item, str)]
        if len(type_values) != len(raw_type):
            raise OpenAPIProcessingError(f"{context}.type must contain only strings.")
        non_null_types = sorted({item for item in type_values if item != "null"})
        if "null" in type_values:
            nullable = True
        if len(non_null_types) == 1:
            normalized_type = non_null_types[0]
        elif len(non_null_types) == 0:
            normalized_type = None
        else:
            raise OpenAPIProcessingError(
                f"{context}.type with multiple non-null values is intentionally deferred."
            )
    else:
        raise OpenAPIProcessingError(f"{context}.type must be a string, array, or missing.")

    format_value = schema_obj.get("format")
    if format_value is not None and not isinstance(format_value, str):
        raise OpenAPIProcessingError(f"{context}.format must be a string when present.")

    enum_value = schema_obj.get("enum")
    normalized_enum: tuple[Any, ...] | None = None
    if enum_value is not None:
        enum_items = _require_sequence(enum_value, context=f"{context}.enum")
        normalized_enum = tuple(
            sorted(
                enum_items, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"))
            )
        )

    required_value = schema_obj.get("required", [])
    required_items = _require_sequence(required_value, context=f"{context}.required")
    required_names: list[str] = []
    for index, required_name in enumerate(required_items):
        if not isinstance(required_name, str):
            raise OpenAPIProcessingError(f"{context}.required[{index}] must be a string.")
        required_names.append(required_name)
    required = tuple(sorted(set(required_names)))

    properties_value = schema_obj.get("properties", {})
    properties_obj = _require_mapping(properties_value, context=f"{context}.properties")
    properties: list[CanonicalSchemaProperty] = []
    for property_name in sorted(properties_obj):
        properties.append(
            CanonicalSchemaProperty(
                name=property_name,
                schema=_normalize_schema(
                    properties_obj[property_name],
                    resolver=resolver,
                    context=f"{context}.properties.{property_name}",
                ),
            )
        )

    items_schema: CanonicalSchema | None = None
    if "items" in schema_obj:
        items_schema = _normalize_schema(
            schema_obj["items"],
            resolver=resolver,
            context=f"{context}.items",
        )

    additional_properties: bool | CanonicalSchema
    raw_additional_properties = schema_obj.get("additionalProperties", True)
    if isinstance(raw_additional_properties, bool):
        additional_properties = raw_additional_properties
    elif isinstance(raw_additional_properties, dict):
        additional_properties = _normalize_schema(
            raw_additional_properties,
            resolver=resolver,
            context=f"{context}.additionalProperties",
        )
    else:
        raise OpenAPIProcessingError(
            f"{context}.additionalProperties must be a boolean or schema object."
        )

    all_of = _normalize_schema_array(
        schema_obj.get("allOf"), resolver=resolver, context=f"{context}.allOf"
    )
    one_of = _normalize_schema_array(
        schema_obj.get("oneOf"), resolver=resolver, context=f"{context}.oneOf"
    )
    any_of = _normalize_schema_array(
        schema_obj.get("anyOf"), resolver=resolver, context=f"{context}.anyOf"
    )

    discriminator = _normalize_discriminator(
        schema_obj.get("discriminator"),
        context=f"{context}.discriminator",
    )

    return CanonicalSchema(
        type=normalized_type,
        format=format_value,
        enum=normalized_enum,
        nullable=nullable,
        required=required,
        properties=tuple(properties),
        items=items_schema,
        additional_properties=additional_properties,
        read_only=bool(schema_obj.get("readOnly", False)),
        write_only=bool(schema_obj.get("writeOnly", False)),
        deprecated=bool(schema_obj.get("deprecated", False)),
        all_of=all_of,
        one_of=one_of,
        any_of=any_of,
        discriminator=discriminator,
    )


def _normalize_schema_array(
    raw_value: object,
    *,
    resolver: _LocalRefResolver,
    context: str,
) -> tuple[CanonicalSchema, ...]:
    if raw_value is None:
        return ()

    schema_items = _require_sequence(raw_value, context=context)
    normalized_items = [
        _normalize_schema(item, resolver=resolver, context=f"{context}[{index}]")
        for index, item in enumerate(schema_items)
    ]
    normalized_items.sort(key=lambda item: serialize_canonical_json(item.to_dict()))
    return tuple(normalized_items)


def _normalize_discriminator(
    raw_discriminator: object, *, context: str
) -> CanonicalDiscriminator | None:
    if raw_discriminator is None:
        return None

    discriminator_obj = _require_mapping(raw_discriminator, context=context)
    property_name = discriminator_obj.get("propertyName")
    if not isinstance(property_name, str) or not property_name:
        raise OpenAPIProcessingError(f"{context}.propertyName must be a non-empty string.")

    mapping_value = discriminator_obj.get("mapping", {})
    mapping_obj = _require_mapping(mapping_value, context=f"{context}.mapping")
    mapping_items: list[tuple[str, str]] = []
    for mapping_key in sorted(mapping_obj):
        mapping_ref = mapping_obj[mapping_key]
        if not isinstance(mapping_ref, str):
            raise OpenAPIProcessingError(f"{context}.mapping.{mapping_key} must be a string.")
        mapping_items.append((mapping_key, mapping_ref))

    return CanonicalDiscriminator(property_name=property_name, mapping=tuple(mapping_items))


class _LocalRefResolver:
    """Resolves local '#/...' references and fails on unsupported external refs."""

    def __init__(self, *, document: Mapping[str, Any]) -> None:
        self._document = document

    def resolve_mapping(
        self,
        value: object,
        *,
        context: str,
        ref_chain: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        resolved = self.resolve(value, context=context, ref_chain=ref_chain)
        return _require_mapping(resolved, context=context)

    def resolve(
        self,
        value: object,
        *,
        context: str,
        ref_chain: tuple[str, ...] = (),
    ) -> object:
        if isinstance(value, dict) and "$ref" in value:
            return self._resolve_ref_object(value, context=context, ref_chain=ref_chain)
        return value

    def _resolve_ref_object(
        self,
        ref_obj: Mapping[str, Any],
        *,
        context: str,
        ref_chain: tuple[str, ...],
    ) -> object:
        sibling_keys = sorted(key for key in ref_obj if key != "$ref")
        if sibling_keys:
            raise OpenAPIProcessingError(
                f"{context}: '$ref' with sibling keys {sibling_keys} is intentionally deferred."
            )

        raw_ref = ref_obj.get("$ref")
        if not isinstance(raw_ref, str):
            raise OpenAPIProcessingError(f"{context}.$ref must be a string.")
        if not raw_ref.startswith("#/"):
            raise OpenAPIProcessingError(
                f"{context}: external ref {raw_ref!r} is not supported in MVP."
            )
        if raw_ref in ref_chain:
            chain_display = " -> ".join((*ref_chain, raw_ref))
            raise OpenAPIProcessingError(f"{context}: cyclic $ref detected ({chain_display}).")

        resolved = self._resolve_local_json_pointer(raw_ref, context=context)
        return self.resolve(
            resolved,
            context=f"{context} -> {raw_ref}",
            ref_chain=(*ref_chain, raw_ref),
        )

    def _resolve_local_json_pointer(self, ref: str, *, context: str) -> object:
        pointer = ref[2:]
        current: object = self._document

        for raw_segment in pointer.split("/"):
            segment = raw_segment.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict):
                if segment not in current:
                    raise OpenAPIProcessingError(
                        f"{context}: unresolved local ref segment {segment!r} in {ref!r}."
                    )
                current = current[segment]
            elif isinstance(current, list):
                if not segment.isdigit():
                    raise OpenAPIProcessingError(
                        f"{context}: invalid array ref segment {segment!r} in {ref!r}."
                    )
                index = int(segment)
                if index < 0 or index >= len(current):
                    raise OpenAPIProcessingError(
                        f"{context}: array ref index {index} out of bounds in {ref!r}."
                    )
                current = current[index]
            else:
                raise OpenAPIProcessingError(
                    f"{context}: unresolved ref {ref!r}; traversed into non-container value."
                )

        return current
