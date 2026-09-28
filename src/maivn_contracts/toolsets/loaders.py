"""Typed validators for ToolSet contract objects."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import TypeAdapter

from maivn_contracts.toolsets.model import ToolSet, ToolSetMember

_TOOL_SET_MEMBER_ADAPTER: TypeAdapter[ToolSetMember] = TypeAdapter[ToolSetMember](
    ToolSetMember,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


def validate_tool_set(obj: Mapping[str, Any]) -> ToolSet:
    """Validate a ToolSet-like mapping and return the typed wire model."""
    return ToolSet.model_validate(obj)


def validate_tool_set_member(obj: Mapping[str, Any]) -> ToolSetMember:
    """Validate a ToolSet member-like mapping and return the typed wire model."""
    return _TOOL_SET_MEMBER_ADAPTER.validate_python(obj)
