"""Form receivers accept bounded explicit fields, never raw browser requests."""

from typing import Any

import pytest
from pydantic import ValidationError

from maivn_contracts.scenarios.connection_events import FormSubmittedEvent


def payload(**changes: Any) -> dict[str, Any]:
    """Build the exact signed form envelope."""
    return {
        'form_id': 'contact',
        'submission_id': 'request-001',
        'submitted_at': '2026-09-05T13:00:00Z',
        'fields': {'email': 'fixture@example.invalid', 'message': 'Help', 'count': 1},
        **changes,
    }


def test_form_fields_roundtrip_without_coercion() -> None:
    """Selected scalar fields and flat lists preserve their actual JSON types."""
    fields = {'values': ['text', 3, 2.5, True, None], 'text': '2', 'flag': False}
    event = FormSubmittedEvent.model_validate(payload(fields=fields))
    assert event.model_dump(mode='json')['fields'] == fields
    assert event.submitted_at.utcoffset() is not None


@pytest.mark.parametrize(
    'changes',
    [
        {'form_id': ''},
        {'form_id': 'bad/name'},
        {'form_id': 'a' * 101},
        {'submission_id': ''},
        {'submission_id': 'a' * 201},
        {'submitted_at': '2026-09-05T13:00:00'},
        {'submitted_at': 123},
        {'submitted_at': '123'},
        {'headers': {'Authorization': 'sentinel'}},
        {'fields': {'file': {'name': 'private.txt', 'content': 'sentinel'}}},
        {'fields': {'nested': [['not-flat']]}},
        {'fields': {'value': float('nan')}},
        {'fields': {'value': float('inf')}},
        {'fields': {'value': 2**53}},
        {'fields': {'text': 'a' * 8193}},
        {'fields': {'list': [0] * 101}},
        {'fields': {str(index): 1 for index in range(101)}},
        {'fields': {'a' * 101: 1}},
        {'fields': {'': 1}},
        {'fields': {'text': '\ud800'}},
        {'fields': {str(index): 'a' * 8192 for index in range(40)}},
    ],
)
def test_form_rejects_unbounded_or_unselected_input(changes: dict[str, Any]) -> None:
    """Invalid envelope data must be refused before signing or persistence."""
    with pytest.raises(ValidationError):
        FormSubmittedEvent.model_validate(payload(**changes))
