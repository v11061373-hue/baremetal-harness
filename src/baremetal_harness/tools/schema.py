from inspect import Parameter, signature
from types import UnionType
from typing import Literal, Union, get_args, get_origin, get_type_hints

from baremetal_harness.core.errors import ToolArgumentsInvalid, ToolSchemaError


def _schema_for_annotation(
    annotation: object,
    parameter_name: str,
) -> dict[str, object]:
    scalar_types: dict[object, str] = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
    }
    if annotation in scalar_types:
        return {"type": scalar_types[annotation]}
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin is list and len(arguments) == 1 and arguments[0] in scalar_types:
        return {
            "type": "array",
            "items": {"type": scalar_types[arguments[0]]},
        }
    if origin is Literal and arguments:
        return {"enum": list(arguments)}
    if origin in {Union, UnionType} and type(None) in arguments:
        non_none = [item for item in arguments if item is not type(None)]
        if len(non_none) == 1:
            return _schema_for_annotation(non_none[0], parameter_name)
    raise ToolSchemaError(
        f"unsupported annotation for {parameter_name}: {annotation!r}"
    )


def schema_for_callable(function) -> dict[str, object]:
    parameters = signature(function).parameters
    hints = get_type_hints(function)
    properties: dict[str, object] = {}
    required: list[str] = []
    for name, parameter in parameters.items():
        if parameter.kind not in {
            Parameter.POSITIONAL_ONLY,
            Parameter.POSITIONAL_OR_KEYWORD,
            Parameter.KEYWORD_ONLY,
        }:
            raise ToolSchemaError(f"unsupported parameter kind for {name}")
        annotation = hints.get(name, parameter.annotation)
        if annotation is Parameter.empty:
            raise ToolSchemaError(f"missing annotation for {name}")
        property_schema = _schema_for_annotation(annotation, name)
        if parameter.default is Parameter.empty:
            required.append(name)
        else:
            property_schema["default"] = parameter.default
        properties[name] = property_schema
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def validate_arguments(
    schema: dict[str, object],
    arguments: dict[str, object],
) -> dict[str, object]:
    properties = schema.get("properties")
    required = schema.get("required", [])
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise ToolArgumentsInvalid("invalid tool schema")
    unknown = set(arguments) - set(properties)
    if unknown:
        raise ToolArgumentsInvalid(f"unknown properties: {sorted(unknown)}")
    missing = [name for name in required if name not in arguments]
    if missing:
        raise ToolArgumentsInvalid(f"missing required properties: {missing}")
    validated = dict(arguments)
    python_types = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
    }
    for name, value in arguments.items():
        property_schema = properties[name]
        if not isinstance(property_schema, dict):
            raise ToolArgumentsInvalid(f"invalid schema for {name}")
        if "enum" in property_schema and value not in property_schema["enum"]:
            raise ToolArgumentsInvalid(f"invalid value for {name}")
        expected_name = property_schema.get("type")
        if expected_name is None:
            continue
        expected = python_types.get(expected_name)
        if expected is None:
            raise ToolArgumentsInvalid(f"unsupported schema type for {name}")
        if expected_name in {"integer", "number"} and isinstance(value, bool):
            raise ToolArgumentsInvalid(f"invalid type for {name}")
        if not isinstance(value, expected):
            raise ToolArgumentsInvalid(f"invalid type for {name}")
    return validated
