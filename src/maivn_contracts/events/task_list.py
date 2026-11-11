"""Bounded full snapshots for an invocation's visible task list."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator


class TaskListItem(BaseModel):
    """A stable task identity, display title and progress state."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    id: Annotated[StrictStr, Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$')]
    title: Annotated[StrictStr, Field(min_length=1, max_length=160, pattern=r'\S')]
    status: Literal['pending', 'in_progress', 'completed']


class TaskListSnapshot(BaseModel):
    """A complete replacement; an empty list clears the previous snapshot."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    items: Annotated[tuple[TaskListItem, ...], Field(max_length=20)]

    @field_validator('items')
    @classmethod
    def require_unique_ids(cls, items: tuple[TaskListItem, ...]) -> tuple[TaskListItem, ...]:
        """Keep one status per task identity."""
        if len({item.id for item in items}) != len(items):
            message = 'task item IDs must be unique'
            raise ValueError(message)
        return items
