"""Additional parser/validator/normalizer branch coverage tests."""

from __future__ import annotations

from typing import Any

import pytest

from app.core.openapi_processing import (
    OpenAPIProcessingError,
    normalize_openapi_document,
    parse_openapi_document,
    validate_openapi_document,
)


def _base_document() -> dict[str, Any]:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Additional Coverage API", "version": "1.0.0"},
        "paths": {},
    }


def _normalize(document: dict[str, Any], *, openapi_version: str = "3.0.3"):
    return normalize_openapi_document(document=document, openapi_version=openapi_version)


def _document_with_operation(*, method: str = "get") -> dict[str, Any]:
    document = _base_document()
    document["paths"] = {
        "/items": {
            method: {
                "responses": {"200": {"description": "ok"}},
            }
        }
    }
    return document


def _document_with_parameters(parameters: object) -> dict[str, Any]:
    document = _document_with_operation(method="get")
    document["paths"]["/items"]["get"]["parameters"] = parameters
    return document


def _document_with_responses(responses: object) -> dict[str, Any]:
    document = _document_with_operation(method="get")
    document["paths"]["/items"]["get"]["responses"] = responses
    return document


def _document_with_request_schema(schema: object) -> dict[str, Any]:
    document = _document_with_operation(method="post")
    document["paths"]["/items"]["post"]["requestBody"] = {
        "required": False,
        "content": {"application/json": {"schema": schema}},
    }
    return document


def test_parse_openapi_document_rejects_non_utf8() -> None:
    with pytest.raises(OpenAPIProcessingError, match="not valid UTF-8"):
        parse_openapi_document(b"\xff\xfe", source="bad-spec")


def test_parse_openapi_document_rejects_non_object_top_level() -> None:
    with pytest.raises(
        OpenAPIProcessingError,
        match="top-level document must be a JSON/YAML object",
    ):
        parse_openapi_document(b"[]", source="bad-spec")


def test_parse_openapi_document_reports_yaml_then_json_failures() -> None:
    with pytest.raises(OpenAPIProcessingError, match="invalid JSON/YAML input") as exc_info:
        parse_openapi_document(b"openapi: [", source="bad-spec")
    message = str(exc_info.value)
    assert "yaml:" in message
    assert "json:" in message


def test_validate_openapi_document_rejects_missing_openapi_field() -> None:
    with pytest.raises(
        OpenAPIProcessingError,
        match="missing or invalid 'openapi' version string",
    ):
        validate_openapi_document({"paths": {}}, source="invalid-doc")


@pytest.mark.parametrize("version", ["3", "x.y", "2.0.0"])
def test_validate_openapi_document_rejects_unsupported_versions(version: str) -> None:
    with pytest.raises(OpenAPIProcessingError, match="unsupported OpenAPI version"):
        validate_openapi_document({"openapi": version, "paths": {}}, source="invalid-doc")


def test_normalize_rejects_invalid_paths_shape_and_keys() -> None:
    document = _base_document()
    document["paths"] = []  # type: ignore[assignment]
    with pytest.raises(OpenAPIProcessingError, match="paths must be an object"):
        _normalize(document)

    document = _base_document()
    document["paths"] = {  # type: ignore[dict-item]
        1: {"get": {"responses": {"200": {"description": "ok"}}}}
    }
    with pytest.raises(OpenAPIProcessingError, match="Path keys must be strings"):
        _normalize(document)

    document = _base_document()
    document["paths"] = {"items": {"get": {"responses": {"200": {"description": "ok"}}}}}
    with pytest.raises(OpenAPIProcessingError, match="expected leading '/'"):
        _normalize(document)


def test_normalize_rejects_non_string_operation_id() -> None:
    document = _document_with_operation(method="get")
    document["paths"]["/items"]["get"]["operationId"] = 123
    with pytest.raises(OpenAPIProcessingError, match="operationId must be a string"):
        _normalize(document)


@pytest.mark.parametrize(
    ("parameters", "message"),
    [
        ({"name": "id"}, "parameters must be an array"),
        (
            [{"name": "", "in": "query", "schema": {"type": "string"}}],
            "name must be a non-empty string",
        ),
        (
            [{"name": "id", "in": "body", "schema": {"type": "string"}}],
            "must be one of",
        ),
        (
            [{"name": "id", "in": "path", "required": False, "schema": {"type": "string"}}],
            "path parameters must declare required=true",
        ),
        (
            [
                {
                    "name": "id",
                    "in": "query",
                    "schema": {"type": "string"},
                    "content": {"application/json": {"schema": {"type": "string"}}},
                }
            ],
            "cannot contain both 'schema' and 'content'",
        ),
        ([{"name": "id", "in": "query"}], "must include either 'schema' or 'content'"),
        (
            [{"name": "id", "in": "query", "content": "not-object"}],
            "content must be an object",
        ),
        (
            [
                {
                    "name": "id",
                    "in": "query",
                    "content": {
                        "application/json": {"schema": {"type": "string"}},
                        "text/plain": {"schema": {"type": "string"}},
                    },
                }
            ],
            "supports exactly one media type in MVP",
        ),
        (
            [{"name": "id", "in": "query", "content": {"application/json": {}}}],
            "must include schema",
        ),
        (
            [
                {"name": "id", "in": "query", "schema": {"type": "string"}},
                {"name": "id", "in": "query", "schema": {"type": "string"}},
            ],
            "duplicate parameter identity",
        ),
        (
            [{"name": "id", "in": "query", "style": 1, "schema": {"type": "string"}}],
            "style must be a string",
        ),
        (
            [{"name": "id", "in": "query", "explode": "yes", "schema": {"type": "string"}}],
            "explode must be a boolean",
        ),
        (
            [{"name": "id", "in": "query", "explode": False, "schema": {"type": "string"}}],
            "intentionally deferred",
        ),
    ],
)
def test_normalize_rejects_invalid_parameter_forms(parameters: object, message: str) -> None:
    with pytest.raises(OpenAPIProcessingError, match=message):
        _normalize(_document_with_parameters(parameters))


@pytest.mark.parametrize(
    ("responses", "message"),
    [
        ({"bad-status": {"description": "x"}}, "not a supported response status key"),
        (
            {"200": {"description": "ok", "headers": {"X-Trace": {"schema": {"type": "string"}}}}},
            "headers is intentionally deferred",
        ),
        (
            {"200": {"description": "ok", "content": {"application/json": {}}}},
            "must include schema",
        ),
    ],
)
def test_normalize_rejects_invalid_response_forms(responses: object, message: str) -> None:
    with pytest.raises(OpenAPIProcessingError, match=message):
        _normalize(_document_with_responses(responses))


def test_normalize_rejects_null_operation_security_override() -> None:
    document = _document_with_operation(method="get")
    document["paths"]["/items"]["get"]["security"] = None
    with pytest.raises(OpenAPIProcessingError, match="security must be an array"):
        _normalize(document)


def test_normalize_rejects_non_string_security_scope() -> None:
    document = _base_document()
    document["security"] = [{"ApiKey": [1]}]
    with pytest.raises(OpenAPIProcessingError, match="must be a string"):
        _normalize(document)


@pytest.mark.parametrize(
    ("scheme_obj", "message"),
    [
        ({"type": 1}, ".type must be a string"),
        ({"type": "custom"}, "is not supported"),
        ({"type": "http", "scheme": 1}, ".scheme must be a string"),
        (
            {"type": "http", "scheme": "bearer", "bearerFormat": 1},
            ".bearerFormat must be a string",
        ),
        ({"type": "apiKey", "name": 1, "in": "header"}, ".name must be a string"),
        ({"type": "apiKey", "name": "X-Api-Key", "in": 1}, ".in must be a string"),
        ({"type": "openIdConnect", "openIdConnectUrl": 1}, ".openIdConnectUrl must be a string"),
        ({"type": "apiKey", "in": "header"}, "apiKey scheme requires valid 'name' and 'in'"),
        ({"type": "http"}, "http scheme requires 'scheme'"),
        ({"type": "openIdConnect"}, "openIdConnect scheme requires openIdConnectUrl"),
        (
            {"type": "oauth2", "flows": {"implicit": {"authorizationUrl": 1, "scopes": {}}}},
            ".authorizationUrl must be a string",
        ),
        (
            {"type": "oauth2", "flows": {"clientCredentials": {"tokenUrl": 1, "scopes": {}}}},
            ".tokenUrl must be a string",
        ),
        (
            {
                "type": "oauth2",
                "flows": {
                    "password": {
                        "tokenUrl": "https://example.com/token",
                        "refreshUrl": 1,
                        "scopes": {},
                    }
                },
            },
            ".refreshUrl must be a string",
        ),
    ],
)
def test_normalize_rejects_invalid_security_scheme_forms(
    scheme_obj: dict[str, Any],
    message: str,
) -> None:
    document = _base_document()
    document["components"] = {"securitySchemes": {"Auth": scheme_obj}}
    with pytest.raises(OpenAPIProcessingError, match=message):
        _normalize(document)


@pytest.mark.parametrize(
    ("schema", "message"),
    [
        ({"not": {}}, "schema keywords"),
        ({"type": ["string", 1]}, "type must contain only strings"),
        ({"type": ["string", "integer"]}, "multiple non-null values is intentionally deferred"),
        ({"type": 123}, "type must be a string, array, or missing"),
        ({"type": "string", "format": 1}, ".format must be a string"),
        ({"type": "object", "required": [1]}, ".required\\[0\\] must be a string"),
        ({"type": "object", "additionalProperties": 5}, "additionalProperties must be a boolean"),
        (
            {"type": "object", "discriminator": {"propertyName": "", "mapping": {}}},
            "propertyName must be a non-empty string",
        ),
        (
            {
                "type": "object",
                "discriminator": {"propertyName": "kind", "mapping": {"dog": 1}},
            },
            ".mapping.dog must be a string",
        ),
    ],
)
def test_normalize_rejects_invalid_schema_forms(schema: dict[str, Any], message: str) -> None:
    with pytest.raises(OpenAPIProcessingError, match=message):
        _normalize(_document_with_request_schema(schema))


def test_normalize_handles_type_array_with_only_null() -> None:
    snapshot = _normalize(_document_with_request_schema({"type": ["null"]}))
    schema = snapshot.operations[0].request_body.media_types[0].schema
    assert schema.type is None
    assert schema.nullable is True


def test_canonical_to_dict_and_checksum_cover_nested_schema_and_security_override() -> None:
    document = _document_with_request_schema(
        {
            "type": "object",
            "additionalProperties": {"type": "integer"},
        }
    )
    document["paths"]["/items"]["post"]["security"] = []

    snapshot = _normalize(document)
    payload = snapshot.to_dict()

    request_schema_payload = payload["operations"][0]["request_body"]["content"][0]["schema"]
    assert isinstance(request_schema_payload["additional_properties"], dict)
    assert payload["operations"][0]["security_override"] == []
    assert len(snapshot.checksum()) == 64


@pytest.mark.parametrize(
    ("schema", "components", "message"),
    [
        (
            {"$ref": "#/components/schemas/Thing", "type": "object"},
            {"schemas": {"Thing": {"type": "object"}}},
            "'\\$ref' with sibling keys",
        ),
        (
            {"$ref": 1},
            {"schemas": {"Thing": {"type": "object"}}},
            "\\$ref must be a string",
        ),
        (
            {"$ref": "https://example.com/schema.yaml"},
            {"schemas": {"Thing": {"type": "object"}}},
            "external ref",
        ),
        (
            {"$ref": "#/components/schemas/Missing"},
            {"schemas": {"Thing": {"type": "object"}}},
            "unresolved local ref segment",
        ),
        (
            {"$ref": "#/components/schemas/not-index"},
            {"schemas": [{"type": "object"}]},
            "invalid array ref segment",
        ),
        (
            {"$ref": "#/components/schemas/5"},
            {"schemas": [{"type": "object"}]},
            "array ref index 5 out of bounds",
        ),
        (
            {"$ref": "#/components/schemas/Leaf/type"},
            {"schemas": {"Leaf": "plain-string"}},
            "traversed into non-container value",
        ),
    ],
)
def test_normalize_rejects_invalid_ref_resolution_paths(
    schema: dict[str, Any],
    components: dict[str, Any],
    message: str,
) -> None:
    document = _document_with_request_schema(schema)
    document["components"] = components
    with pytest.raises(OpenAPIProcessingError, match=message):
        _normalize(document)


def test_normalize_rejects_cyclic_local_refs() -> None:
    document = _document_with_request_schema({"$ref": "#/components/schemas/A"})
    document["components"] = {
        "schemas": {
            "A": {"$ref": "#/components/schemas/B"},
            "B": {"$ref": "#/components/schemas/A"},
        }
    }
    with pytest.raises(OpenAPIProcessingError, match="cyclic \\$ref detected"):
        _normalize(document)
