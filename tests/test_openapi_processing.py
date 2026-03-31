"""Unit tests for OpenAPI parsing, validation, and canonical normalization."""

from __future__ import annotations

import json

import pytest

from app.core.openapi_processing import OpenAPIProcessingError, parse_validate_and_normalize_openapi
from tests.fixtures.invalid_specs import (
    deferred_parameter_style_spec,
    invalid_json_bytes,
    invalid_openapi_missing_info,
    unresolved_local_ref_spec,
)


def _build_base_spec() -> dict:
    return {
        "openapi": "3.0.3",
        "info": {"title": "API", "version": "1.0.0"},
        "paths": {},
    }


def _to_json_bytes(spec: dict) -> bytes:
    return json.dumps(spec).encode("utf-8")


def test_parse_validate_normalize_rejects_invalid_json_and_yaml() -> None:
    with pytest.raises(OpenAPIProcessingError, match="invalid JSON/YAML input"):
        parse_validate_and_normalize_openapi(invalid_json_bytes(), source="spec-under-test")


def test_parse_validate_normalize_rejects_invalid_openapi() -> None:
    with pytest.raises(OpenAPIProcessingError, match="invalid OpenAPI document"):
        parse_validate_and_normalize_openapi(
            _to_json_bytes(invalid_openapi_missing_info()),
            source="spec-under-test",
        )


def test_normalization_parameter_identity_is_name_and_in() -> None:
    spec = _build_base_spec()
    spec["paths"] = {
        "/pets/{id}": {
            "parameters": [
                {
                    "name": "trace",
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string"},
                },
                {
                    "name": "id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                },
            ],
            "get": {
                "responses": {"200": {"description": "ok"}},
                "parameters": [
                    {
                        "name": "trace",
                        "in": "header",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
            },
        }
    }

    snapshot = parse_validate_and_normalize_openapi(_to_json_bytes(spec), source="spec-under-test")
    operation = snapshot.operations[0]

    assert [(parameter.name, parameter.location) for parameter in operation.parameters] == [
        ("id", "path"),
        ("trace", "header"),
    ]
    trace_parameter = [
        parameter for parameter in operation.parameters if parameter.name == "trace"
    ][0]
    assert trace_parameter.origin == "operation"
    assert trace_parameter.required is True


def test_request_body_required_survives_normalization() -> None:
    spec = _build_base_spec()
    spec["paths"] = {
        "/pets": {
            "post": {
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"type": "object", "properties": {"name": {"type": "string"}}}
                        }
                    },
                },
                "responses": {"201": {"description": "created"}},
            }
        }
    }

    snapshot = parse_validate_and_normalize_openapi(_to_json_bytes(spec), source="spec-under-test")
    operation = snapshot.operations[0]

    assert operation.request_body.present is True
    assert operation.request_body.required is True


def test_media_type_separation_is_preserved() -> None:
    spec = _build_base_spec()
    spec["paths"] = {
        "/upload": {
            "post": {
                "requestBody": {
                    "required": False,
                    "content": {
                        "application/json": {"schema": {"type": "object"}},
                        "application/xml": {"schema": {"type": "string"}},
                    },
                },
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {"schema": {"type": "object"}},
                            "text/plain": {"schema": {"type": "string"}},
                        },
                    }
                },
            }
        }
    }

    snapshot = parse_validate_and_normalize_openapi(_to_json_bytes(spec), source="spec-under-test")
    operation = snapshot.operations[0]

    assert [item.media_type for item in operation.request_body.media_types] == [
        "application/json",
        "application/xml",
    ]
    assert [item.media_type for item in operation.responses[0].media_types] == [
        "application/json",
        "text/plain",
    ]


def test_read_only_write_only_and_additional_properties_are_represented() -> None:
    spec = _build_base_spec()
    spec["paths"] = {
        "/users": {
            "post": {
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["id", "profile"],
                                "properties": {
                                    "id": {"type": "string", "readOnly": True},
                                    "secret": {"type": "string", "writeOnly": True},
                                    "nickname": {"type": "string", "nullable": True},
                                    "profile": {
                                        "type": "object",
                                        "additionalProperties": {"type": "integer"},
                                    },
                                },
                            }
                        }
                    }
                },
                "responses": {"200": {"description": "ok"}},
            }
        }
    }

    snapshot = parse_validate_and_normalize_openapi(_to_json_bytes(spec), source="spec-under-test")
    schema = snapshot.operations[0].request_body.media_types[0].schema
    properties = {item.name: item.schema for item in schema.properties}

    assert properties["id"].read_only is True
    assert properties["secret"].write_only is True
    assert properties["nickname"].nullable is True
    assert isinstance(properties["profile"].additional_properties, type(schema))
    assert properties["profile"].additional_properties.type == "integer"  # type: ignore[union-attr]


def test_nullable_from_31_type_array_is_represented() -> None:
    spec = _build_base_spec()
    spec["openapi"] = "3.1.0"
    spec["paths"] = {
        "/users": {
            "post": {
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "nickname": {"type": ["string", "null"]},
                                },
                            }
                        }
                    }
                },
                "responses": {"200": {"description": "ok"}},
            }
        }
    }

    snapshot = parse_validate_and_normalize_openapi(_to_json_bytes(spec), source="spec-under-test")
    schema = snapshot.operations[0].request_body.media_types[0].schema
    properties = {item.name: item.schema for item in schema.properties}
    assert properties["nickname"].nullable is True


def test_all_of_one_of_any_of_and_discriminator_are_represented() -> None:
    spec = _build_base_spec()
    spec["components"] = {
        "schemas": {
            "Dog": {"type": "object", "properties": {"bark": {"type": "boolean"}}},
            "Cat": {"type": "object", "properties": {"meow": {"type": "boolean"}}},
        }
    }
    spec["paths"] = {
        "/animals": {
            "get": {
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "allOf": [
                                        {
                                            "type": "object",
                                            "properties": {"kind": {"type": "string"}},
                                        },
                                        {
                                            "type": "object",
                                            "properties": {"age": {"type": "integer"}},
                                        },
                                    ],
                                    "oneOf": [
                                        {"$ref": "#/components/schemas/Dog"},
                                        {"$ref": "#/components/schemas/Cat"},
                                    ],
                                    "anyOf": [
                                        {
                                            "type": "object",
                                            "properties": {"friendly": {"type": "boolean"}},
                                        },
                                        {
                                            "type": "object",
                                            "properties": {"trained": {"type": "boolean"}},
                                        },
                                    ],
                                    "discriminator": {
                                        "propertyName": "kind",
                                        "mapping": {
                                            "dog": "#/components/schemas/Dog",
                                            "cat": "#/components/schemas/Cat",
                                        },
                                    },
                                }
                            }
                        },
                    }
                },
            }
        }
    }

    snapshot = parse_validate_and_normalize_openapi(_to_json_bytes(spec), source="spec-under-test")
    schema = snapshot.operations[0].responses[0].media_types[0].schema

    assert len(schema.all_of) == 2
    assert len(schema.one_of) == 2
    assert len(schema.any_of) == 2
    assert schema.discriminator is not None
    assert schema.discriminator.property_name == "kind"
    assert schema.discriminator.mapping == (
        ("cat", "#/components/schemas/Cat"),
        ("dog", "#/components/schemas/Dog"),
    )


def test_stable_ordering_for_paths_methods_params_responses_and_operations() -> None:
    spec = _build_base_spec()
    spec["paths"] = {
        "/z-path": {
            "post": {
                "responses": {
                    "default": {"description": "fallback"},
                    "2XX": {"description": "range"},
                    "200": {"description": "ok"},
                },
                "parameters": [
                    {"name": "b", "in": "query", "required": False, "schema": {"type": "string"}},
                    {"name": "a", "in": "query", "required": False, "schema": {"type": "string"}},
                ],
            }
        },
        "/a-path": {
            "get": {
                "responses": {"201": {"description": "created"}},
            }
        },
    }

    snapshot = parse_validate_and_normalize_openapi(_to_json_bytes(spec), source="spec-under-test")
    serialized_first = snapshot.to_dict()
    serialized_second = parse_validate_and_normalize_openapi(
        _to_json_bytes(spec),
        source="spec-under-test",
    ).to_dict()

    assert [operation["path"] for operation in serialized_first["operations"]] == [
        "/a-path",
        "/z-path",
    ]
    operation_two = serialized_first["operations"][1]
    assert [item["name"] for item in operation_two["parameters"]] == ["a", "b"]
    assert [item["status_code"] for item in operation_two["responses"]] == [
        "200",
        "2XX",
        "default",
    ]
    assert serialized_first == serialized_second


def test_unresolved_local_ref_fails_explicitly() -> None:
    with pytest.raises(OpenAPIProcessingError, match="unresolved \\$ref"):
        parse_validate_and_normalize_openapi(
            _to_json_bytes(unresolved_local_ref_spec()),
            source="spec-under-test",
        )


def test_response_schema_preserves_directional_read_only_write_only() -> None:
    spec = _build_base_spec()
    spec["paths"] = {
        "/users": {
            "get": {
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string", "readOnly": True},
                                        "internalNote": {"type": "string", "writeOnly": True},
                                    },
                                }
                            }
                        },
                    }
                },
            }
        }
    }

    snapshot = parse_validate_and_normalize_openapi(_to_json_bytes(spec), source="spec-under-test")
    response_schema = snapshot.operations[0].responses[0].media_types[0].schema
    properties = {item.name: item.schema for item in response_schema.properties}

    assert properties["id"].read_only is True
    assert properties["id"].write_only is False
    assert properties["internalNote"].write_only is True
    assert properties["internalNote"].read_only is False


def test_parameter_style_and_explode_non_default_fail_loudly() -> None:
    with pytest.raises(OpenAPIProcessingError, match="intentionally deferred"):
        parse_validate_and_normalize_openapi(
            _to_json_bytes(deferred_parameter_style_spec()),
            source="spec-under-test",
        )
