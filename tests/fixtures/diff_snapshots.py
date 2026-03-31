"""Focused fixture builders for deterministic diff engine tests."""

from __future__ import annotations

import json
from typing import Any

from app.core.openapi_processing import (
    CanonicalOpenAPISnapshot,
    parse_validate_and_normalize_openapi,
)


def _base_spec() -> dict[str, Any]:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Diff Fixtures API", "version": "1.0.0"},
        "paths": {},
    }


def _to_snapshot(spec: dict[str, Any], *, source: str = "fixture") -> CanonicalOpenAPISnapshot:
    raw = json.dumps(spec).encode("utf-8")
    return parse_validate_and_normalize_openapi(raw, source=source)


def build_operation_surface_snapshots() -> tuple[
    CanonicalOpenAPISnapshot, CanonicalOpenAPISnapshot
]:
    old_spec = _base_spec()
    old_spec["paths"] = {
        "/pets": {
            "get": {
                "deprecated": False,
                "responses": {"200": {"description": "ok"}},
            },
            "post": {"responses": {"201": {"description": "created"}}},
        },
        "/users": {"get": {"responses": {"200": {"description": "ok"}}}},
    }
    new_spec = _base_spec()
    new_spec["paths"] = {
        "/pets": {
            "get": {
                "deprecated": True,
                "responses": {"200": {"description": "ok"}},
            },
            "patch": {"responses": {"200": {"description": "updated"}}},
        },
        "/teams": {"get": {"responses": {"200": {"description": "ok"}}}},
    }
    return _to_snapshot(old_spec, source="old"), _to_snapshot(new_spec, source="new")


def build_parameter_change_snapshots() -> tuple[CanonicalOpenAPISnapshot, CanonicalOpenAPISnapshot]:
    old_spec = _base_spec()
    old_spec["paths"] = {
        "/pets/{id}": {
            "parameters": [
                {
                    "name": "trace",
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string"},
                }
            ],
            "get": {
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
                    {
                        "name": "status",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string"},
                    },
                    {
                        "name": "limit",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "integer"},
                    },
                    {
                        "name": "sort",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string"},
                    },
                    {
                        "name": "trace",
                        "in": "header",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                ],
                "responses": {"200": {"description": "ok"}},
            },
        }
    }

    new_spec = _base_spec()
    new_spec["paths"] = {
        "/pets/{id}": {
            "parameters": [
                {
                    "name": "trace",
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string"},
                }
            ],
            "get": {
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
                    {
                        "name": "status",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "integer"},
                    },
                    {
                        "name": "offset",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "integer"},
                    },
                    {
                        "name": "limit",
                        "in": "header",
                        "required": False,
                        "schema": {"type": "integer"},
                    },
                ],
                "responses": {"200": {"description": "ok"}},
            },
        }
    }
    return _to_snapshot(old_spec, source="old"), _to_snapshot(new_spec, source="new")


def build_request_change_snapshots() -> tuple[CanonicalOpenAPISnapshot, CanonicalOpenAPISnapshot]:
    old_spec = _base_spec()
    old_spec["paths"] = {
        "/users": {
            "post": {
                "requestBody": {
                    "required": False,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["name"],
                                "properties": {
                                    "name": {"type": "string"},
                                    "age": {"type": "integer"},
                                    "role": {"type": "string", "enum": ["admin", "user", "guest"]},
                                    "legacyField": {"type": "string"},
                                    "nickname": {"type": "string", "nullable": True},
                                    "internalId": {"type": "string", "readOnly": True},
                                    "profile": {
                                        "type": "object",
                                        "additionalProperties": {"type": "integer"},
                                    },
                                },
                                "additionalProperties": True,
                            }
                        },
                        "application/xml": {"schema": {"type": "string"}},
                    },
                },
                "responses": {"201": {"description": "created"}},
            }
        }
    }

    new_spec = _base_spec()
    new_spec["paths"] = {
        "/users": {
            "post": {
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["name", "age"],
                                "properties": {
                                    "name": {"type": "string"},
                                    "age": {"type": "number"},
                                    "role": {"type": "string", "enum": ["admin", "user"]},
                                    "nickname": {"type": "string", "nullable": False},
                                    "internalId": {"type": "string", "writeOnly": True},
                                    "tags": {"type": "array", "items": {"type": "string"}},
                                    "profile": {
                                        "type": "object",
                                        "additionalProperties": False,
                                    },
                                },
                                "additionalProperties": False,
                            }
                        },
                        "text/plain": {"schema": {"type": "string"}},
                    },
                },
                "responses": {"201": {"description": "created"}},
            }
        }
    }
    return _to_snapshot(old_spec, source="old"), _to_snapshot(new_spec, source="new")


def build_response_change_snapshots() -> tuple[CanonicalOpenAPISnapshot, CanonicalOpenAPISnapshot]:
    old_spec = _base_spec()
    old_spec["paths"] = {
        "/users/{id}": {
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "get": {
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "name": {"type": "string"},
                                        "role": {"type": "string", "enum": ["admin", "user"]},
                                        "nickname": {"type": "string", "nullable": False},
                                        "internalNote": {"type": "string", "writeOnly": True},
                                        "meta": {"type": "object", "additionalProperties": True},
                                    },
                                    "additionalProperties": False,
                                }
                            },
                            "application/xml": {"schema": {"type": "string"}},
                        },
                    },
                    "204": {"description": "empty"},
                    "default": {"description": "fallback"},
                }
            },
        }
    }

    new_spec = _base_spec()
    new_spec["paths"] = {
        "/users/{id}": {
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "get": {
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "integer"},
                                        "role": {
                                            "type": "string",
                                            "enum": ["admin", "user", "guest"],
                                        },
                                        "nickname": {"type": "string", "nullable": True},
                                        "internalNote": {"type": "string", "readOnly": True},
                                        "meta": {
                                            "type": "object",
                                            "additionalProperties": {"type": "integer"},
                                        },
                                        "createdAt": {"type": "string", "format": "date-time"},
                                    },
                                    "additionalProperties": True,
                                }
                            },
                            "text/plain": {"schema": {"type": "string"}},
                        },
                    },
                    "201": {"description": "created"},
                }
            },
        }
    }
    return _to_snapshot(old_spec, source="old"), _to_snapshot(new_spec, source="new")


def build_security_change_snapshots() -> tuple[CanonicalOpenAPISnapshot, CanonicalOpenAPISnapshot]:
    old_spec = _base_spec()
    old_spec["components"] = {
        "securitySchemes": {
            "BearerAuth": {"type": "http", "scheme": "bearer"},
            "ApiKeyAuth": {"type": "apiKey", "name": "X-API-KEY", "in": "header"},
        }
    }
    old_spec["security"] = [{"BearerAuth": []}]
    old_spec["paths"] = {
        "/admin": {
            "get": {
                "security": [{"ApiKeyAuth": []}],
                "responses": {"200": {"description": "ok"}},
            }
        }
    }

    new_spec = _base_spec()
    new_spec["components"] = {
        "securitySchemes": {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            },
            "OAuth2": {
                "type": "oauth2",
                "flows": {
                    "clientCredentials": {
                        "tokenUrl": "https://example.com/token",
                        "scopes": {"admin:read": "Read"},
                    }
                },
            },
        }
    }
    new_spec["security"] = [{"OAuth2": ["admin:read"]}]
    new_spec["paths"] = {
        "/admin": {
            "get": {
                "security": [{"BearerAuth": []}],
                "responses": {"200": {"description": "ok"}},
            }
        }
    }
    return _to_snapshot(old_spec, source="old"), _to_snapshot(new_spec, source="new")


def build_composition_change_snapshots() -> tuple[
    CanonicalOpenAPISnapshot, CanonicalOpenAPISnapshot
]:
    old_spec = _base_spec()
    old_spec["components"] = {
        "schemas": {
            "Dog": {"type": "object", "properties": {"bark": {"type": "boolean"}}},
            "Cat": {"type": "object", "properties": {"meow": {"type": "boolean"}}},
        }
    }
    old_spec["paths"] = {
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
                                        }
                                    ],
                                    "oneOf": [{"$ref": "#/components/schemas/Dog"}],
                                    "anyOf": [{"$ref": "#/components/schemas/Cat"}],
                                    "discriminator": {
                                        "propertyName": "kind",
                                        "mapping": {"dog": "#/components/schemas/Dog"},
                                    },
                                }
                            }
                        },
                    }
                }
            }
        }
    }

    new_spec = _base_spec()
    new_spec["components"] = old_spec["components"]
    new_spec["paths"] = {
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
                                    "anyOf": [{"$ref": "#/components/schemas/Dog"}],
                                    "discriminator": {
                                        "propertyName": "species",
                                        "mapping": {"cat": "#/components/schemas/Cat"},
                                    },
                                }
                            }
                        },
                    }
                }
            }
        }
    }
    return _to_snapshot(old_spec, source="old"), _to_snapshot(new_spec, source="new")


def build_request_body_presence_snapshots() -> tuple[
    CanonicalOpenAPISnapshot, CanonicalOpenAPISnapshot
]:
    old_spec = _base_spec()
    old_spec["paths"] = {
        "/echo": {
            "post": {
                "responses": {"200": {"description": "ok"}},
            }
        }
    }
    new_spec = _base_spec()
    new_spec["paths"] = {
        "/echo": {
            "post": {
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"type": "object", "properties": {"v": {"type": "string"}}}
                        }
                    },
                },
                "responses": {"200": {"description": "ok"}},
            }
        }
    }
    return _to_snapshot(old_spec, source="old"), _to_snapshot(new_spec, source="new")


def build_request_body_removed_snapshots() -> tuple[
    CanonicalOpenAPISnapshot, CanonicalOpenAPISnapshot
]:
    old_snapshot, new_snapshot = build_request_body_presence_snapshots()
    return new_snapshot, old_snapshot
