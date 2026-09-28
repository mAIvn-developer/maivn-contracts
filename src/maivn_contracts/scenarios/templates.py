"""Literal, single-pass event interpolation shared by hosted and served triggers."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import TypeGuard

_PLACEHOLDER = re.compile(r'\{\{\s*event(?:\.([^{}]+?))?\s*\}\}')


def _is_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    return isinstance(value, Mapping)


def render_event_template(template: str, payload: Mapping[str, object]) -> str:
    """Resolve event paths literally; retain missing paths and never render field content."""

    def replace(match: re.Match[str]) -> str:
        current: object = payload
        path = match.group(1)
        if path is not None:
            for segment in path.strip().split('.'):
                if not _is_mapping(current) or segment not in current:
                    return match.group(0)
                current = current[segment]
        return (
            current
            if isinstance(current, str)
            else json.dumps(current, sort_keys=True, default=str)
        )

    return _PLACEHOLDER.sub(replace, template)
