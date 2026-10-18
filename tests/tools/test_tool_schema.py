from typing import Literal

import pytest

from baremetal_harness.core.errors import ToolArgumentsInvalid, ToolSchemaError
from baremetal_harness.tools.schema import schema_for_callable, validate_arguments


def read_file(path: str, max_bytes: int = 4096) -> str:
    return path


def test_schema_for_typed_callable() -> None:
    assert schema_for_callable(read_file) == {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "max_bytes": {"type": "integer", "default": 4096},
        },
        "required": ["path"],
        "additionalProperties": False,
    }


def test_schema_supports_literal_and_scalar_lists() -> None:
    def choose(mode: Literal["fast", "safe"], paths: list[str]) -> str:
        return mode

    schema = schema_for_callable(choose)

    assert schema["properties"]["mode"] == {"enum": ["fast", "safe"]}
    assert schema["properties"]["paths"] == {
        "type": "array",
        "items": {"type": "string"},
    }


def test_unsupported_annotation_fails_closed() -> None:
    def invalid(value: dict[str, str]) -> None:
        return None

    with pytest.raises(ToolSchemaError, match="value"):
        schema_for_callable(invalid)


def test_validation_rejects_boolean_for_integer() -> None:
    schema = schema_for_callable(read_file)

    with pytest.raises(ToolArgumentsInvalid, match="max_bytes"):
        validate_arguments(schema, {"path": "README.md", "max_bytes": True})
