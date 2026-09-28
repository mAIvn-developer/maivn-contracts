"""Typed loaders and validators for deployed-agent registry contract files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import TypeAdapter

from maivn_contracts.agents.model import Agent, AgentVersion, MessageBinding

_CONTRACTS_ROOT = Path(__file__).resolve().parents[3] / 'agents'
_MESSAGE_BINDING_ADAPTER: TypeAdapter[MessageBinding] = TypeAdapter[MessageBinding](
    MessageBinding,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


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


def load_agent_schema() -> dict[str, Any]:
    """Load the deployed Agent JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'agent.schema.json')


def load_agent_version_schema() -> dict[str, Any]:
    """Load the immutable AgentVersion JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'agent_version.schema.json')


def load_message_binding_schema() -> dict[str, Any]:
    """Load the MessageBinding JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'message_binding.schema.json')


def validate_agent(obj: Mapping[str, Any]) -> Agent:
    """Validate an agent-like mapping and return the typed wire model."""
    schema = load_agent_schema()
    _check_schema(schema)
    validator = _build_validator(schema)
    validator.validate(obj)
    return Agent.model_validate(obj)


def validate_agent_version(obj: Mapping[str, Any]) -> AgentVersion:
    """Validate an agent-version-like mapping and return the typed wire model."""
    schema = load_agent_version_schema()
    _check_schema(schema)
    validator = _build_validator(schema)
    validator.validate(obj)
    return AgentVersion.model_validate(obj)


def validate_message_binding(obj: Mapping[str, Any]) -> MessageBinding:
    """Validate a message-binding-like mapping and return the typed wire model."""
    schema = load_message_binding_schema()
    _check_schema(schema)
    validator = _build_validator(schema)
    validator.validate(obj)
    return _MESSAGE_BINDING_ADAPTER.validate_python(obj)


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
