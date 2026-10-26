"""Typed registration labels; a label describes authority required, never grants it."""

from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictBool

ToolPermission: TypeAlias = Literal[
    'read', 'write', 'delete', 'export', 'import', 'admin', 'impersonate'
]
PRIVILEGED_TOOL_PERMISSIONS = frozenset({'delete', 'import', 'admin', 'impersonate'})


class ToolSafetyLabels(BaseModel):
    """Immutable developer registration metadata shared by snapshots and tool specs."""

    model_config = ConfigDict(extra='forbid', frozen=True)
    permissions: tuple[ToolPermission, ...] | None = Field(default=None)
    destructive: StrictBool | None = Field(default=None)

    @property
    def requires_approval(self) -> bool:
        """Ordinary explicit registrations remain authorized; privilege needs approval."""
        return self.destructive is True or bool(
            PRIVILEGED_TOOL_PERMISSIONS.intersection(self.permissions or ())
        )
