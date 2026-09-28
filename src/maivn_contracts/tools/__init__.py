"""Owned tool contract loaders, validators, and typed models.

This module owns the public Python interface for `libraries/maivn-contracts/tools`.
It depends only on the checked-in JSON contract files, Pydantic, and
jsonschema. Tool call ids compose with the public Message contract through
`Message.metadata.tool_call_id`.
"""

from __future__ import annotations

from maivn_contracts.tools.loaders import (
    load_tool_call_schema,
    load_tool_callback_schema,
    load_tool_dispatch_schema,
    load_tool_outcome_schema,
    load_tool_spec_schema,
    validate_tool_call,
    validate_tool_callback,
    validate_tool_dispatch,
    validate_tool_outcome,
    validate_tool_spec,
)
from maivn_contracts.tools.model import (
    AuthRef,
    ErrorToolOutcome,
    FunctionToolSpec,
    IdempotencyHint,
    MCPRegistryServerRef,
    MCPServerRef,
    MCPToolSpec,
    MCPUrlServerRef,
    OkToolOutcome,
    SystemToolSpec,
    ToolArgumentDependency,
    ToolArgumentProducerRequirement,
    ToolCall,
    ToolCallback,
    ToolCallLineage,
    ToolDependencyEdge,
    ToolDispatch,
    ToolOutcome,
    ToolOutcomeArtifactRef,
    ToolOutcomeError,
    ToolOutcomeVariant,
    ToolSpec,
    ToolSpecRef,
    ToolSpecVariant,
)

__all__ = [
    'AuthRef',
    'ErrorToolOutcome',
    'FunctionToolSpec',
    'IdempotencyHint',
    'MCPRegistryServerRef',
    'MCPServerRef',
    'MCPToolSpec',
    'MCPUrlServerRef',
    'OkToolOutcome',
    'SystemToolSpec',
    'ToolArgumentDependency',
    'ToolArgumentProducerRequirement',
    'ToolCall',
    'ToolCallLineage',
    'ToolCallback',
    'ToolDependencyEdge',
    'ToolDispatch',
    'ToolOutcome',
    'ToolOutcomeArtifactRef',
    'ToolOutcomeError',
    'ToolOutcomeVariant',
    'ToolSpec',
    'ToolSpecRef',
    'ToolSpecVariant',
    'load_tool_call_schema',
    'load_tool_callback_schema',
    'load_tool_dispatch_schema',
    'load_tool_outcome_schema',
    'load_tool_spec_schema',
    'validate_tool_call',
    'validate_tool_callback',
    'validate_tool_dispatch',
    'validate_tool_outcome',
    'validate_tool_spec',
]
