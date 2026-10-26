"""Choice domains take precedence over model-authored presentation."""

import pytest

from maivn_contracts.runtime.choice_options import choice_values, resolve_choice_options


@pytest.mark.parametrize('multiple', [False, True])
def test_declared_domain_preserves_rich_associations_and_fills_missing_values(
    *, multiple: bool
) -> None:
    """Reordered labels and invalid hints cannot change the allowed values."""
    scalar = {'type': 'string', 'enum': ['east', 'west', 'Other']}
    schema = {'type': 'array', 'items': scalar} if multiple else scalar
    assert resolve_choice_options(
        schema,
        [
            {'label': 'Europe', 'value': 'west', 'description': 'EU residency'},
            {'label': 'east', 'description': 'Low latency'},
            {'label': 'West (fast)', 'description': 'Invalid association'},
        ],
    ) == (
        {'label': 'east', 'value': 'east', 'description': 'Low latency'},
        {'label': 'Europe', 'value': 'west', 'description': 'EU residency'},
        {'label': 'Other', 'value': 'Other', 'description': ''},
    )


def test_open_choices_keep_explicit_values_and_remove_duplicate_submissions() -> None:
    """Legacy labels remain values while explicit machine identifiers can differ."""
    assert resolve_choice_options(
        {'type': 'string'},
        [
            {'label': 'European deployment', 'value': 'west', 'description': 'EU'},
            {'label': 'Alias', 'value': 'west', 'description': 'Same value'},
            {'label': 'Legacy', 'description': 'No value field'},
        ],
    ) == (
        {'label': 'European deployment', 'value': 'west', 'description': 'EU'},
        {'label': 'Legacy', 'value': 'Legacy', 'description': 'No value field'},
    )


def test_empty_and_long_declared_values_are_not_limited_by_model_label_bounds() -> None:
    """Application enums remain complete even beyond model-authored presentation limits."""
    values = ['', *[f'value-{i}' for i in range(20)], 'long-' * 40]
    assert [option['value'] for option in resolve_choice_options({'enum': values}, [])] == values


@pytest.mark.parametrize(
    'schema',
    [
        {'type': 'array', 'items': 'not-a-schema'},
        {'enum': []},
        {'enum': 'abc'},
        {'enum': ['a', 1]},
        {'type': 'string'},
    ],
)
def test_choice_values_refuse_to_invent_a_domain(schema: dict[str, object]) -> None:
    """Only a non-empty all-string enum (or array item enum) is a choice domain."""
    assert choice_values(schema) is None


def test_options_without_string_label_or_value_are_skipped() -> None:
    """An option whose label or value is not text never becomes a choice."""
    options: list[dict[str, object]] = [
        {'label': 7, 'value': 'a'},
        {'label': 'A', 'value': 3},
        {'label': 'B', 'value': 'b', 'description': 4},
    ]
    assert resolve_choice_options({'type': 'string'}, options) == (
        {'label': 'B', 'value': 'b', 'description': ''},
    )
