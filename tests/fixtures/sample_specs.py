"""Small deterministic OpenAPI specs for integration/smoke tests."""

from __future__ import annotations


def build_valid_spec_json(*, title: str, include_patch: bool = False) -> bytes:
    patch_part = (
        """
            "patch": {
                "responses": {"200": {"description": "updated"}}
            },
        """
        if include_patch
        else ""
    )
    return f"""
{{
  "openapi": "3.0.3",
  "info": {{"title": "{title}", "version": "1.0.0"}},
  "paths": {{
    "/pets": {{
      "get": {{
        "responses": {{
          "200": {{
            "description": "ok",
            "content": {{
              "application/json": {{
                "schema": {{
                  "type": "object",
                  "properties": {{
                    "status": {{"type": "string", "enum": ["active", "disabled"]}}
                  }}
                }}
              }}
            }}
          }}
        }}
      }},
      {patch_part}
      "post": {{
        "requestBody": {{
          "required": false,
          "content": {{
            "application/json": {{
              "schema": {{
                "type": "object",
                "properties": {{
                  "name": {{"type": "string"}}
                }}
              }}
            }}
          }}
        }},
        "responses": {{"201": {{"description": "created"}}}}
      }}
    }}
  }}
}}
""".encode()


def build_valid_spec_yaml(title: str) -> bytes:
    return (f"openapi: 3.0.3\ninfo:\n  title: {title}\n  version: 1.0.0\npaths: {{}}\n").encode()
