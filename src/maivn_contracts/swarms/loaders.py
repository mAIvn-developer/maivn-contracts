"""Typed validators for Swarm contract objects."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from maivn_contracts.swarms.model import Swarm

if TYPE_CHECKING:
    from collections.abc import Mapping


def validate_swarm(obj: Mapping[str, Any]) -> Swarm:
    """Validate a Swarm-like mapping and return the typed wire model."""
    return Swarm.model_validate(obj)
