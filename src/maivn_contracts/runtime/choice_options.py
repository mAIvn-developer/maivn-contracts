"""Resolve follow-up presentation against the effective answer value domain."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast


def choice_values(schema: Mapping[str, object]) -> tuple[str, ...] | None:
    """Return an explicit string domain, including array item enums, without inventing one."""
    value_schema = schema.get('items') if schema.get('type') == 'array' else schema
    if not isinstance(value_schema, Mapping):
        return None
    values = cast('Mapping[str, object]', value_schema).get('enum')
    if not isinstance(values, (list, tuple)) or not values:
        return None
    if not all(isinstance(value, str) for value in cast('Sequence[object]', values)):
        return None
    return tuple(cast('Sequence[str]', values))


def resolve_choice_options(
    schema: Mapping[str, object],
    options: Sequence[Mapping[str, object]],
    *,
    fill_missing: bool = True,
) -> tuple[dict[str, str], ...]:
    """Preserve explicit associations; never infer them from order or similar labels.

    Stored presentation can stay sparse. Clients fill missing declared choices
    without applying model-authored label or option-count bounds to app schemas.
    """
    values = choice_values(schema)
    by_value: dict[str, dict[str, str]] = {}
    for option in options:
        label = option.get('label')
        value = option.get('value')
        if value is None:
            value = label
        if not isinstance(label, str) or not isinstance(value, str):
            continue
        if value in by_value or (values is not None and value not in values):
            continue
        description = option.get('description')
        by_value[value] = {
            'label': label,
            'value': value,
            'description': description if isinstance(description, str) else '',
        }
    if values is None or not fill_missing:
        return tuple(by_value.values())
    return tuple(
        by_value.get(value, {'label': value, 'value': value, 'description': ''})
        for value in dict.fromkeys(values)
    )
