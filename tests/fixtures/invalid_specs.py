"""Small invalid OpenAPI fixture builders for parser/normalizer tests."""

from __future__ import annotations

from typing import Any


def invalid_json_bytes() -> bytes:
    return b'{"openapi":'


def invalid_openapi_missing_info() -> dict[str, Any]:
    return {"openapi": "3.0.3", "paths": {}}


def unresolved_local_ref_spec() -> dict[str, Any]:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Invalid Ref API", "version": "1.0.0"},
        "paths": {
            "/pets": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Missing"}
                                }
                            },
                        }
                    },
                }
            }
        },
    }


def deferred_parameter_style_spec() -> dict[str, Any]:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Deferred Style API", "version": "1.0.0"},
        "paths": {
            "/users": {
                "get": {
                    "parameters": [
                        {
                            "name": "tags",
                            "in": "query",
                            "required": False,
                            "style": "pipeDelimited",
                            "schema": {"type": "array", "items": {"type": "string"}},
                        }
                    ],
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
