"""Run task-list snapshots use the same bounds in the event model and schema."""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from maivn_contracts.events import Event, validate_event

_ITEM = {'id': 'collect-inputs', 'title': 'Collect inputs', 'status': 'pending'}


def _event(items: list[dict[str, str]], **lineage: Any) -> dict[str, Any]:
    return {
        'event_id': 'evt-task-list',
        'ordinal': 'agent-1',
        'type': 'task_list_updated',
        'session_id': 'ses-root',
        'root_event_id': 'evt-root',
        'correlation_id': 'call-tasks',
        'trigger_chain_depth': 0,
        'job_depth': 0,
        'job_index': 0,
        'actor': 'agent',
        'mode': 'hosted',
        'payload': {'items': items},
        'ts': '2026-11-07T00:00:00Z',
        **lineage,
    }


@pytest.mark.parametrize('items', [[], [_ITEM]])
def test_root_snapshot_including_clear_is_a_canonical_event(items: list[dict[str, str]]) -> None:
    """Both contract layers accept complete snapshots and empty replacements."""
    event = validate_event(_event(items))
    assert event.model_dump(mode='json')['payload'] == {'items': items}


@pytest.mark.parametrize(
    'items',
    [
        [{**_ITEM, 'id': 'with space'}],
        [{**_ITEM, 'id': 'a' * 49}],
        [{**_ITEM, 'title': ' '}],
        [{**_ITEM, 'title': 'x' * 161}],
        [{**_ITEM, 'status': 'finished'}],
        [{**_ITEM, 'extra': 'unexpected'}],
        [{**_ITEM, 'id': f'a{i}'} for i in range(21)],
    ],
)
def test_invalid_task_items_are_rejected_by_model_and_schema(items: list[dict[str, str]]) -> None:
    """Enforce the size, identity, title and state bounds at both boundaries."""
    payload = _event(items)
    with pytest.raises(SchemaValidationError):
        validate_event(payload)
    with pytest.raises(ValidationError):
        Event.model_validate(payload)


def test_duplicate_item_identity_is_refused_even_when_title_differs() -> None:
    """An item ID can describe only one task in the snapshot."""
    with pytest.raises(ValidationError, match='unique'):
        Event.model_validate(_event([_ITEM, {**_ITEM, 'title': 'Another task'}]))


@pytest.mark.parametrize(
    'lineage',
    [
        {'parent_session_id': 'ses-parent'},
        {'parent_assignment_uuid': 'assignment-parent'},
        {'job_depth': 1},
        {'correlation_id': None},
        {'correlation_id': ' '},
        {'correlation_id': '\t'},
    ],
)
def test_updates_require_a_root_and_tool_call_identity(lineage: dict[str, Any]) -> None:
    """Reject uncorrelated updates and any descendant's mutation."""
    payload = _event([_ITEM], **lineage)
    with pytest.raises(SchemaValidationError):
        validate_event(payload)
    with pytest.raises(ValidationError):
        Event.model_validate(payload)
