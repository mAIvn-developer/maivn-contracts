# pyright: strict
"""Unit tests for the curated durable session replay assembly."""

from __future__ import annotations

from typing import Any, NamedTuple

from maivn_contracts.events import Event, assemble_session_replay


class _PositionedEvent(NamedTuple):
    position: int
    event: Event


_FIRST_POSITION = 5
_LAST_POSITION = 12


def _event(
    index: int,
    event_type: str,
    *,
    session_id: str = 'ses-replay',
    parent_session_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> Event:
    return Event.model_validate(
        {
            'event_id': f'evt-replay-{index}',
            'ordinal': f'producer-replay-{index:06d}',
            'type': event_type,
            'session_id': session_id,
            'parent_session_id': parent_session_id,
            'root_event_id': 'evt-replay-root',
            'trigger_id': 'trg-replay',
            'trigger_chain_depth': 1,
            'parent_assignment_uuid': 'assign-parent',
            'job_depth': 2,
            'job_index': index,
            'actor': 'agent:replay-test',
            'mode': 'hosted',
            'correlation_id': f'corr-{index}',
            'payload': payload or {},
            'latency_ms': 37,
            'ts': f'2026-07-15T12:00:{index:02d}Z',
        },
    )


def test_replay_preserves_durable_position_order_for_shuffled_input() -> None:
    """Replay order follows the append cursor, not caller or timestamp order."""
    replay = assemble_session_replay(
        [
            _PositionedEvent(30, _event(3, 'final', payload={'stop_reason': 'end_turn'})),
            _PositionedEvent(10, _event(1, 'assignment_received')),
            _PositionedEvent(20, _event(2, 'status_message', payload={'message': 'Working'})),
        ],
        session_id='ses-replay',
    )

    assert [frame.position for frame in replay.frames] == [10, 20, 30]
    assert [frame.kind for frame in replay.frames] == [
        'assignment_received',
        'status_message',
        'final',
    ]


def test_replay_exposes_curated_tool_fields_without_arguments_or_results() -> None:
    """Tool replay includes identity/status/timing but never tool payload content."""
    replay = assemble_session_replay(
        [
            _PositionedEvent(
                4,
                _event(
                    4,
                    'system_tool_complete',
                    payload={
                        'tool_name': 'search_documents',
                        'arguments': {'query': 'private query'},
                        'result': 'private result',
                    },
                ),
            ),
        ],
        session_id='ses-replay',
    )

    frame = replay.frames[0]
    assert frame.summary == {
        'tool_name': 'search_documents',
        'status': 'completed',
        'duration_ms': 37,
    }
    rendered = replay.model_dump_json()
    assert 'arguments' not in rendered
    assert 'private query' not in rendered
    assert 'result' not in rendered
    assert 'private result' not in rendered


def test_replay_coverage_tracks_positions_and_drop_reasons() -> None:
    """Coverage spans dropped durable events and counts each table disposition reason."""
    replay = assemble_session_replay(
        [
            _PositionedEvent(_LAST_POSITION, _event(12, 'memory_retrieved')),
            _PositionedEvent(
                _FIRST_POSITION,
                _event(5, 'status_message_chunk', payload={'text': 'secret'}),
            ),
            _PositionedEvent(9, _event(9, 'final', payload={'usage': {'output_tokens': 2}})),
        ],
        session_id='ses-replay',
    )

    assert replay.coverage.first_position == _FIRST_POSITION
    assert replay.coverage.last_position == _LAST_POSITION
    assert replay.coverage.dropped_count_by_reason == {
        'Raw chunks and deltas are not durable replay frames.': 1,
        'Memory internals are not visible in session replay.': 1,
    }
    assert [frame.position for frame in replay.frames] == [9]
