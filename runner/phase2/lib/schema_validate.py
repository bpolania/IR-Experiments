from __future__ import annotations

from typing import Any


class SchemaValidationError(ValueError):
    pass


def _resolve_ref(schema_root: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise SchemaValidationError(f"unsupported $ref: {ref}")
    node: Any = schema_root
    for token in ref[2:].split("/"):
        if not isinstance(node, dict) or token not in node:
            raise SchemaValidationError(f"unresolvable $ref: {ref}")
        node = node[token]
    if not isinstance(node, dict):
        raise SchemaValidationError(f"$ref did not resolve to object schema: {ref}")
    return node


def _check_type(value: Any, allowed_type: str) -> bool:
    if allowed_type == "object":
        return isinstance(value, dict)
    if allowed_type == "array":
        return isinstance(value, list)
    if allowed_type == "string":
        return isinstance(value, str)
    if allowed_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if allowed_type == "number":
        return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)
    if allowed_type == "boolean":
        return isinstance(value, bool)
    if allowed_type == "null":
        return value is None
    raise SchemaValidationError(f"unsupported schema type: {allowed_type}")


def _validate(value: Any, schema: dict[str, Any], root: dict[str, Any], path: str) -> None:
    if "$ref" in schema:
        resolved = _resolve_ref(root, schema["$ref"])
        _validate(value, resolved, root, path)
        return

    if "type" in schema:
        type_decl = schema["type"]
        types = type_decl if isinstance(type_decl, list) else [type_decl]
        if not any(_check_type(value, t) for t in types):
            raise SchemaValidationError(f"{path}: expected type {types}, got {type(value).__name__}")

    if "enum" in schema and value not in schema["enum"]:
        raise SchemaValidationError(f"{path}: value not in enum")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise SchemaValidationError(f"{path}: value {value} < minimum {schema['minimum']}")

    if isinstance(value, dict):
        props = schema.get("properties", {})
        required = schema.get("required", [])
        for req_key in required:
            if req_key not in value:
                raise SchemaValidationError(f"{path}: missing required key {req_key}")

        additional_allowed = schema.get("additionalProperties", True)
        if additional_allowed is False:
            unknown = [k for k in value.keys() if k not in props]
            if unknown:
                raise SchemaValidationError(f"{path}: additionalProperties not allowed: {unknown}")

        for k, v in value.items():
            if k in props:
                _validate(v, props[k], root, f"{path}.{k}")

    if isinstance(value, list):
        if "items" in schema:
            for idx, item in enumerate(value):
                _validate(item, schema["items"], root, f"{path}[{idx}]")


def validate_json_schema_instance(instance: dict[str, Any], schema: dict[str, Any]) -> None:
    _validate(instance, schema, schema, "$")
