"""Typed loaders and validators for owned Message contract files."""

from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING, Any, Protocol, cast

from jsonschema import Draft202012Validator, FormatChecker

from maivn_contracts._schema_root import SCHEMA_ROOT
from maivn_contracts.artifacts import load_artifact_ref_schema
from maivn_contracts.messages.model import Attachment, Message

_CONTRACTS_ROOT = SCHEMA_ROOT / 'messages'
_ARTIFACT_REF_SCHEMA_ID = 'https://schemas.maivn.dev/artifacts/artifact_ref.schema.json'

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path


class _JsonSchemaValidator(Protocol):
    """Protocol for the typed validator method used by this module."""

    def validate(self, instance: object) -> None:
        """Validate an object against the configured JSON Schema."""


class _ContractObjectTypeError(TypeError, ValueError):
    """Raised when a contract file is not a JSON object."""

    def __init__(self, path: Path) -> None:
        """Build the invalid contract object error."""
        message = f'Contract file must contain a JSON object: {path}'
        super().__init__(message)


def load_attachment_schema() -> dict[str, Any]:
    """Load the Attachment JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'attachment.schema.json')


def load_message_schema() -> dict[str, Any]:
    """Load the Message JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'message.schema.json')


def validate_attachment(obj: Mapping[str, Any]) -> Attachment:
    """Validate an attachment-like mapping and return the typed wire model."""
    schema = load_attachment_schema()
    _check_schema(schema)
    validator = _build_validator(schema)
    validator.validate(obj)
    return Attachment.model_validate(obj)


def validate_message(obj: Mapping[str, Any]) -> Message:
    """Validate a message-like mapping and return the typed wire model."""
    schema = materialize_message_schema(load_message_schema())
    _check_schema(schema)
    validator = _build_validator(schema)
    validator.validate(obj)
    return Message.model_validate(obj)


def _read_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(loaded, dict):
        raise _ContractObjectTypeError(path)
    return cast('dict[str, Any]', loaded)


def _check_schema(schema: Mapping[str, Any]) -> None:
    check_schema = cast('Callable[[object], None]', Draft202012Validator.check_schema)
    check_schema(schema)


def _build_validator(schema: Mapping[str, Any]) -> _JsonSchemaValidator:
    validator_factory = cast('Callable[..., _JsonSchemaValidator]', Draft202012Validator)
    return validator_factory(schema, format_checker=FormatChecker())


def materialize_message_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline canonical ArtifactRef for this schema and its composite consumers."""
    materialized = copy.deepcopy(schema)
    artifact_schema = copy.deepcopy(load_artifact_ref_schema())
    artifact_schema = _rebase_artifact_ref_definitions(artifact_schema)
    artifact_schema.pop('$id', None)
    artifact_schema.pop('$schema', None)
    definitions = cast('dict[str, Any]', materialized.setdefault('$defs', {}))
    definitions['artifactRef'] = artifact_schema
    serialized = json.dumps(materialized).replace(
        f'"{_ARTIFACT_REF_SCHEMA_ID}"', '"#/$defs/artifactRef"'
    )
    loaded = json.loads(serialized)
    if not isinstance(loaded, dict):
        raise _ContractObjectTypeError(_CONTRACTS_ROOT / 'message.schema.json')
    return cast('dict[str, Any]', loaded)


def _rebase_artifact_ref_definitions(schema: dict[str, Any]) -> dict[str, Any]:
    serialized = json.dumps(schema).replace('"#/$defs/', '"#/$defs/artifactRef/$defs/')
    loaded = json.loads(serialized)
    if not isinstance(loaded, dict):
        raise _ContractObjectTypeError(_CONTRACTS_ROOT / 'message.schema.json')
    return cast('dict[str, Any]', loaded)
