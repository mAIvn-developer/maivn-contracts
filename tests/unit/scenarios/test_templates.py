"""Event interpolation is literal and consistent for hosted and served work."""

import json

import pytest

from maivn_contracts.scenarios.templates import render_event_template


@pytest.mark.parametrize(
    ('template', 'expected'),
    [
        ('{{ event.nested.text }}', 'literal {{event.secret}}'),
        ('{{event.nested.text}} {{event.secret}}', 'literal {{event.secret}} value'),
        ('{{event.missing}}', '{{event.missing}}'),
        ('{{event.flag}} {{event.empty}}', 'false null'),
        ('{{event.items}}', '[1, "two"]'),
        ('{{event.secret}}/{{event.secret}}', 'value/value'),
        ('{{other.secret}}', '{{other.secret}}'),
    ],
)
def test_event_interpolation_preserves_literal_values(template: str, expected: str) -> None:
    """Only placeholders in the original template are interpreted."""
    payload = {
        'nested': {'text': 'literal {{event.secret}}'},
        'secret': 'value',
        'flag': False,
        'empty': None,
        'items': [1, 'two'],
    }
    assert render_event_template(template, payload) == expected


def test_entire_event_is_available_as_json() -> None:
    """A default event template carries the complete event, including nested data."""
    payload = {'nested': {'text': '{{event.secret}}'}, 'number': 2}
    assert json.loads(render_event_template('{{ event }}', payload)) == payload
