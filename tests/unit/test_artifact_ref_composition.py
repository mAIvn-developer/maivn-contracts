# pyright: strict
"""Focused behavior tests for canonical ArtifactRef composition surfaces."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema.exceptions import ValidationError
from pydantic import ValidationError as PydanticValidationError

from maivn_contracts.messages import validate_message
from maivn_contracts.runtime import StartCommand, validate_command
from maivn_contracts.tools import (
    validate_tool_callback,
    validate_tool_outcome,
)
from maivn_contracts.workers import validate_worker_frame

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / 'fixtures'


def _artifact_refs() -> tuple[dict[str, Any], dict[str, Any]]:
    """Load one ordinary and one vault-private canonical wire reference."""
    loaded = json.loads((_FIXTURES_DIR / 'valid_artifact_refs.json').read_text(encoding='utf-8'))
    refs = cast('list[dict[str, Any]]', loaded)
    return copy.deepcopy(refs[0]), copy.deepcopy(refs[1])


def _outcome(artifact_refs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build a successful ToolOutcome with an optional wire-preserved list."""
    outcome: dict[str, Any] = {
        'call_id': 'call-artifact-001',
        'status': 'ok',
        'duration_ms': 42,
        'result': {'summary': 'generated'},
    }
    if artifact_refs is not None:
        outcome['artifact_refs'] = artifact_refs
    return outcome


def _message(artifact_refs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build a minimal Message with an optional wire-preserved list."""
    message: dict[str, Any] = {
        'message_id': 'msg-artifact-001',
        'role': 'assistant',
        'content': 'Your requested artifacts are ready.',
        'ts': '2026-08-09T00:02:00Z',
    }
    if artifact_refs is not None:
        message['artifact_refs'] = artifact_refs
    return message


def test_tool_outcome_roundtrips_ordered_ordinary_and_private_artifact_refs() -> None:
    """Prevent replacing canonical refs with legacy storage-coordinate records."""
    ordinary, private = _artifact_refs()
    outcome = _outcome([private, ordinary])

    validated = validate_tool_outcome(outcome)

    assert validated.model_dump(mode='json', exclude_none=True) == outcome
    assert [ref.artifact_id for ref in validated.artifact_refs or []] == [
        'art_private_0001',
        'art_ordinary_0001',
    ]


def test_message_roundtrips_ordered_ordinary_and_private_artifact_refs() -> None:
    """Prevent Message artifact lists from losing canonical custody-specific fields."""
    ordinary, private = _artifact_refs()
    message = _message([ordinary, private])

    validated = validate_message(message)

    assert validated.model_dump(mode='json', exclude_none=True) == message
    assert [ref.custody for ref in validated.artifact_refs or []] == ['ordinary', 'vault_private']


@pytest.mark.parametrize(
    ('builder', 'validator'),
    [(_outcome, validate_tool_outcome), (_message, validate_message)],
)
def test_artifact_refs_preserve_omission_and_explicit_empty_list(
    builder: Any,
    validator: Any,
) -> None:
    """Keep historical omission absent while preserving an explicit compatibility empty list."""
    omitted = builder()
    explicit_empty = builder([])

    omitted_validated = validator(omitted)
    explicit_empty_validated = validator(explicit_empty)

    assert omitted_validated.artifact_refs is None
    assert omitted_validated.model_dump(mode='json', exclude_none=True) == omitted
    assert explicit_empty_validated.artifact_refs == ()
    assert explicit_empty_validated.model_dump(mode='json', exclude_none=True) == explicit_empty


@pytest.mark.parametrize(
    'forbidden_field', ['storage_ref', 'provider_id', 'signed_url', 'capability', 'grant']
)
@pytest.mark.parametrize(
    ('builder', 'validator'),
    [(_outcome, validate_tool_outcome), (_message, validate_message)],
)
def test_artifact_refs_reject_legacy_storage_and_capability_fields(
    forbidden_field: str,
    builder: Any,
    validator: Any,
) -> None:
    """Reject non-public transport and storage details in nested artifact references."""
    ordinary, _private = _artifact_refs()
    ordinary[forbidden_field] = {'bucket': 'private-bucket'}

    with pytest.raises(ValidationError):
        validator(builder([ordinary]))


def test_tool_outcome_allows_empty_and_rejects_more_than_thirty_two_artifact_refs() -> None:
    """Pin ToolOutcome's compatibility empty-list and bounded candidate-list semantics."""
    ordinary, _private = _artifact_refs()

    assert validate_tool_outcome(_outcome([])).artifact_refs == ()
    with pytest.raises(ValidationError):
        validate_tool_outcome(_outcome([ordinary] * 33))


def test_message_rejects_duplicate_identity_and_more_than_thirty_two_artifact_refs() -> None:
    """Prevent selection ambiguity while retaining the supplied list order."""
    ordinary, private = _artifact_refs()

    with pytest.raises((ValidationError, PydanticValidationError)):
        validate_message(_message([ordinary, copy.deepcopy(ordinary)]))
    refs = [{**private, 'artifact_id': f'private-{index}'} for index in range(33)]
    assert len(validate_message(_message(refs[:32])).artifact_refs or ()) == 32  # noqa: PLR2004 - public wire bound.
    with pytest.raises(ValidationError):
        validate_message(_message(refs))


def test_artifact_ref_collections_are_immutable_after_validation() -> None:
    """Prevent post-validation mutation from bypassing bounds and duplicate checks."""
    ordinary, private = _artifact_refs()
    outcome = validate_tool_outcome(_outcome([ordinary] * 32))
    message = validate_message(_message([ordinary, private]))

    assert isinstance(outcome.artifact_refs, tuple)
    assert isinstance(message.artifact_refs, tuple)
    assert outcome.artifact_refs is not None
    assert message.artifact_refs is not None
    with pytest.raises(AttributeError):
        cast('Any', outcome.artifact_refs).append(ordinary)
    with pytest.raises(AttributeError):
        cast('Any', message.artifact_refs).append(copy.deepcopy(ordinary))


def test_runtime_command_loader_materializes_canonical_message_artifact_refs() -> None:
    """Prevent unresolved canonical refs when runtime embeds Message for validation."""
    ordinary, private = _artifact_refs()
    command = {'kind': 'start', 'messages': [_message([ordinary, private])]}

    validated = validate_command(command)

    assert isinstance(validated, StartCommand)
    assert (
        validated.messages[0].model_dump(mode='json', exclude_none=True) == command['messages'][0]
    )


def test_callback_and_worker_loaders_materialize_canonical_tool_outcome_artifact_refs() -> None:
    """Prevent callback and worker compositions from leaving ArtifactRef refs unresolved."""
    ordinary, private = _artifact_refs()
    callback = {
        'schema_version': 1,
        'dispatch_id': 'dispatch-artifact-001',
        'attempt_id': 'attempt-artifact-001',
        'session_id': 'session-artifact-001',
        'call_id': 'call-artifact-001',
        'completed_at': '2026-08-09T00:03:00Z',
        'outcome': _outcome([ordinary, private]),
    }
    worker_frame = {
        'protocol_version': 1,
        'type': 'tool_result',
        'frame_id': 'frame-artifact-001',
        'sent_at': '2026-08-09T00:03:00Z',
        'payload': {'callback': callback},
        'frame_hmac': '00',
    }

    callback_validated = validate_tool_callback(callback)
    worker_validated = validate_worker_frame(worker_frame)

    callback_outcome = callback_validated.outcome.model_dump(mode='json', exclude_none=True)
    assert callback_outcome == callback['outcome']
    assert worker_validated.payload == worker_frame['payload']
