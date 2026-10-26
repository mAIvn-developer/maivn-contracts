# pyright: strict
"""Focused lifecycle payload and Event-boundary contract tests."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from jsonschema.exceptions import ValidationError
from pydantic import ValidationError as PydanticValidationError

from maivn_contracts.artifacts import (
    ARTIFACT_LIFECYCLE_EVENT_TYPES,
    parse_artifact_lifecycle_event_payload,
    validate_artifact_lifecycle_event_payload,
)
from maivn_contracts.events import Event, assemble_session_audit, validate_event

if TYPE_CHECKING:
    from collections.abc import Mapping

_ERROR = {
    'code': 'artifact_validation_failed',
    'error_class': 'validation',
    'retryable': False,
}
_FIXTURES = Path(__file__).resolve().parents[2] / 'fixtures'


def _fixture(name: str) -> list[dict[str, Any]]:
    loaded = json.loads((_FIXTURES / name).read_text(encoding='utf-8'))
    assert isinstance(loaded, list)
    return cast('list[dict[str, Any]]', loaded)


def _event(
    payload: Mapping[str, object], event_type: str = 'artifact.available'
) -> dict[str, object]:
    return {
        'event_id': 'evt-artifact-001',
        'ordinal': 'producer-artifact-001',
        'type': event_type,
        'session_id': 'session-artifact-001',
        'root_event_id': 'evt-artifact-root-001',
        'trigger_chain_depth': 0,
        'job_depth': 0,
        'job_index': 0,
        'actor': 'artifact-service',
        'mode': 'hosted',
        'payload': payload,
        'ts': '2026-08-09T00:00:00Z',
    }


def _payloads() -> dict[str, dict[str, object]]:
    reservation = {'reservation_id': 'reservation-001', 'logical_output_id': 'output-001'}
    artifact = {
        'artifact_id': 'artifact-001',
        'logical_output_id': 'output-001',
        'revision': 1,
        'custody': 'ordinary',
    }
    delivery = {
        **artifact,
        'delivery_id': 'delivery-001',
        'destination_ref_id': 'destination-001',
    }
    deletion = {**artifact, 'deletion_id': 'deletion-001'}
    intent = {'intent_id': 'intent-001', 'correlation_id': 'correlation-001'}
    return {
        'artifact.reserved': {
            'event_type': 'artifact.reserved',
            **reservation,
            'reservation_state': 'reserved',
            'policy_snapshot_id': 'policy-001',
        },
        'artifact.uploaded': {
            'event_type': 'artifact.uploaded',
            **reservation,
            'reservation_state': 'uploading',
            'upload_receipt_id': 'upload-receipt-001',
        },
        'artifact.validation_started': {
            'event_type': 'artifact.validation_started',
            **reservation,
            'reservation_state': 'validating',
            'validation_profile': 'document-default',
        },
        'artifact.validated': {
            'event_type': 'artifact.validated',
            **reservation,
            'reservation_state': 'validating',
            'validation_receipt_id': 'validation-receipt-001',
        },
        'artifact.available': {
            'event_type': 'artifact.available',
            **artifact,
            'artifact_state': 'available',
        },
        'artifact.rejected': {
            'event_type': 'artifact.rejected',
            **reservation,
            'reservation_state': 'rejected',
            'error': _ERROR,
        },
        'artifact.failed': {
            'event_type': 'artifact.failed',
            **reservation,
            'reservation_state': 'failed',
            'error': _ERROR,
        },
        'artifact.selected': {
            'event_type': 'artifact.selected',
            **artifact,
            'selection_id': 'selection-001',
        },
        'artifact.delivery_queued': {
            'event_type': 'artifact.delivery_queued',
            **delivery,
            'delivery_state': 'queued',
        },
        'artifact.delivery_started': {
            'event_type': 'artifact.delivery_started',
            **delivery,
            'delivery_state': 'started',
        },
        'artifact.delivery_succeeded': {
            'event_type': 'artifact.delivery_succeeded',
            **delivery,
            'delivery_state': 'succeeded',
        },
        'artifact.delivery_failed': {
            'event_type': 'artifact.delivery_failed',
            **delivery,
            'delivery_state': 'failed',
            'error': _ERROR,
        },
        'artifact.expired': {
            'event_type': 'artifact.expired',
            **artifact,
            'artifact_state': 'expired',
        },
        'artifact.deletion_requested': {
            'event_type': 'artifact.deletion_requested',
            **deletion,
            'artifact_state': 'deleting',
        },
        'artifact.deletion_started': {
            'event_type': 'artifact.deletion_started',
            **deletion,
            'artifact_state': 'deleting',
        },
        'artifact.deletion_pending_backup_expiry': {
            'event_type': 'artifact.deletion_pending_backup_expiry',
            **deletion,
            'custody': 'vault_private',
            'artifact_state': 'deletion_pending_backup_expiry',
            'deletion_receipt_id': 'deletion-receipt-001',
        },
        'artifact.deleted': {
            'event_type': 'artifact.deleted',
            **deletion,
            'artifact_state': 'deleted',
            'deletion_receipt_id': 'deletion-receipt-001',
        },
        'artifact.delete_incomplete': {
            'event_type': 'artifact.delete_incomplete',
            **deletion,
            'artifact_state': 'delete_incomplete',
            'deletion_receipt_id': 'deletion-receipt-001',
            'error': _ERROR,
        },
        'artifact.vault_authorization_pending': {
            'event_type': 'artifact.vault_authorization_pending',
            **intent,
            'intent_state': 'authorization_pending',
        },
        'artifact.vault_authorization_denied': {
            'event_type': 'artifact.vault_authorization_denied',
            **intent,
            'intent_state': 'authorization_denied',
            'error': _ERROR,
        },
        'artifact.vault_render_started': {
            'event_type': 'artifact.vault_render_started',
            **intent,
            'intent_state': 'rendering_in_vault',
        },
        'artifact.vault_render_failed': {
            'event_type': 'artifact.vault_render_failed',
            **intent,
            'intent_state': 'render_failed',
            'error': _ERROR,
        },
    }


@pytest.mark.parametrize(('event_type', 'payload'), _payloads().items())
def test_every_lifecycle_variant_roundtrips_through_both_authorities_and_event(
    event_type: str,
    payload: dict[str, object],
) -> None:
    """Pin every lifecycle discriminator across schema, direct model, and outer Event."""
    assert set(_payloads()) == ARTIFACT_LIFECYCLE_EVENT_TYPES
    assert validate_artifact_lifecycle_event_payload(payload).model_dump(mode='json') == payload
    assert parse_artifact_lifecycle_event_payload(payload).model_dump(mode='json') == payload
    assert validate_event(_event(payload, event_type)).payload == payload
    assert Event.model_validate(_event(payload, event_type)).payload == payload


@pytest.mark.parametrize(('event_type', 'payload'), _payloads().items())
def test_every_lifecycle_variant_has_an_exact_required_field_inventory(
    event_type: str,
    payload: dict[str, object],
) -> None:
    """Adding optional fields or weakening required fields must fail the public contract suite."""
    direct = parse_artifact_lifecycle_event_payload(payload)
    assert set(type(direct).model_fields) == set(payload)

    unexpected = dict(payload)
    unexpected['metadata'] = cast('object', {})
    with pytest.raises(ValidationError):
        validate_artifact_lifecycle_event_payload(unexpected)
    with pytest.raises(PydanticValidationError):
        parse_artifact_lifecycle_event_payload(unexpected)

    for field in payload:
        missing = {key: value for key, value in payload.items() if key != field}
        with pytest.raises(ValidationError):
            validate_artifact_lifecycle_event_payload(missing)
        with pytest.raises(PydanticValidationError):
            parse_artifact_lifecycle_event_payload(missing)

    if 'error' not in payload:
        unexpected_error = {**payload, 'error': _ERROR}
        with pytest.raises(ValidationError):
            validate_artifact_lifecycle_event_payload(unexpected_error)
        with pytest.raises(PydanticValidationError):
            parse_artifact_lifecycle_event_payload(unexpected_error)

    assert direct.event_type == event_type


@pytest.mark.parametrize(
    ('event_type', 'wrong_state'),
    [
        ('artifact.delivery_queued', 'started'),
        ('artifact.delivery_started', 'succeeded'),
        ('artifact.delivery_succeeded', 'queued'),
    ],
)
def test_delivery_discriminators_pin_the_exact_state_in_schema_and_direct_models(
    event_type: str,
    wrong_state: str,
) -> None:
    """Delivery event names cannot be paired with another delivery state."""
    payload = deepcopy(_payloads()[event_type])
    payload['delivery_state'] = wrong_state
    with pytest.raises(ValidationError):
        validate_artifact_lifecycle_event_payload(payload)
    with pytest.raises(PydanticValidationError):
        parse_artifact_lifecycle_event_payload(payload)


def test_available_custody_and_state_are_bound_in_schema_and_direct_models() -> None:
    """Ordinary and vault availability states cannot cross custody boundaries."""
    payload = deepcopy(_payloads()['artifact.available'])
    payload['artifact_state'] = 'available_in_vault'
    with pytest.raises(ValidationError):
        validate_artifact_lifecycle_event_payload(payload)
    with pytest.raises(PydanticValidationError):
        parse_artifact_lifecycle_event_payload(payload)


@pytest.mark.parametrize(
    'forbidden_field',
    ['filename', 'storage_ref', 'provider_id', 'signed_url', 'capability', 'exception_repr'],
)
def test_lifecycle_payloads_structurally_reject_sensitive_fields(
    forbidden_field: str,
) -> None:
    """Lifecycle projections never admit storage, capability, provider, or content fields."""
    payload = deepcopy(_payloads()['artifact.available'])
    payload[forbidden_field] = 'private-value'
    with pytest.raises(ValidationError):
        validate_artifact_lifecycle_event_payload(payload)
    with pytest.raises(PydanticValidationError):
        parse_artifact_lifecycle_event_payload(payload)


def test_lifecycle_errors_are_closed_and_value_free() -> None:
    """Failure events expose only the stable ArtifactError triple."""
    payload = deepcopy(_payloads()['artifact.failed'])
    error = payload['error']
    assert isinstance(error, dict)
    error['message'] = 'private provider failure'
    with pytest.raises(ValidationError):
        validate_artifact_lifecycle_event_payload(payload)
    with pytest.raises(PydanticValidationError):
        parse_artifact_lifecycle_event_payload(payload)


def test_artifact_event_remains_a_mapping_for_safe_audit_projection() -> None:
    """Typed validation must not break existing projection consumers that call payload.get."""
    event = Event.model_validate(_event(_payloads()['artifact.available']))
    audit = assemble_session_audit([event], session_id=event.session_id)

    assert event.payload.get('artifact_id') == 'artifact-001'
    assert len(audit.entries) == 1
    assert audit.entries[0].resource == 'artifact:artifact-001'
    assert audit.entries[0].details == {
        'artifact_id': 'artifact-001',
        'logical_output_id': 'output-001',
        'revision': 1,
        'custody': 'ordinary',
        'artifact_state': 'available',
    }


def test_validated_artifact_event_payload_cannot_be_mutated_after_admission() -> None:
    """Frozen lifecycle mappings prevent post-validation type and sensitive-field bypasses."""
    event = Event.model_validate(_event(_payloads()['artifact.failed'], 'artifact.failed'))

    with pytest.raises(TypeError):
        cast('Any', event.payload)['event_type'] = 'artifact.deleted'
    with pytest.raises(TypeError):
        cast('Any', event.payload)['filename'] = 'secret.pdf'
    error = event.payload['error']
    with pytest.raises(TypeError):
        error['message'] = 'private failure'

    rendered = event.model_dump(mode='json')
    assert rendered['payload'] == _payloads()['artifact.failed']
    assert 'secret.pdf' not in event.model_dump_json()
    copied = event.model_copy(deep=True)
    assert copied.model_dump(mode='json') == rendered
    assert copied.payload is event.payload


def test_audit_projection_preserves_allowlisted_uppercase_opaque_ids() -> None:
    """Value-free opaque identifiers remain auditable without relaxing reason-code grammar."""
    payload = deepcopy(_payloads()['artifact.validated'])
    payload['reservation_id'] = 'ReservationA'
    payload['logical_output_id'] = 'OutputA'
    payload['validation_receipt_id'] = 'ReceiptA'
    event = Event.model_validate(_event(payload, 'artifact.validated'))

    audit = assemble_session_audit([event], session_id=event.session_id)

    assert audit.entries[0].resource == 'artifact_reservation:ReservationA'
    assert audit.entries[0].details == {
        'reservation_id': 'ReservationA',
        'logical_output_id': 'OutputA',
        'reservation_state': 'validating',
        'validation_receipt_id': 'ReceiptA',
    }


@pytest.mark.parametrize('payload', _fixture('valid_artifact_lifecycle_events.json'))
def test_valid_lifecycle_fixtures_roundtrip(payload: dict[str, Any]) -> None:
    """Checked-in valid lifecycle fixtures remain canonical round trips."""
    assert validate_artifact_lifecycle_event_payload(payload).model_dump(mode='json') == payload


@pytest.mark.parametrize('payload', _fixture('invalid_artifact_lifecycle_events.json'))
def test_invalid_lifecycle_fixtures_are_rejected(payload: dict[str, Any]) -> None:
    """Checked-in unsafe or mismatched lifecycle fixtures remain invalid."""
    with pytest.raises(ValidationError):
        validate_artifact_lifecycle_event_payload(payload)


def test_available_lifecycle_payload_roundtrips_through_its_own_loader_and_event() -> None:
    """Prevent artifact availability from falling back to the generic open Event payload."""
    payload = {
        'event_type': 'artifact.available',
        'artifact_id': 'artifact-001',
        'logical_output_id': 'output-001',
        'revision': 1,
        'custody': 'ordinary',
        'artifact_state': 'available',
    }

    lifecycle = validate_artifact_lifecycle_event_payload(payload)
    event = validate_event(_event(payload))

    assert lifecycle.model_dump(mode='json') == payload
    assert event.payload == payload


@pytest.mark.parametrize(
    'payload',
    [
        {'event_type': 'artifact.available'},
        {
            'event_type': 'artifact.available',
            'artifact_id': 'artifact-001',
            'logical_output_id': 'output-001',
            'revision': 1,
            'custody': 'ordinary',
            'artifact_state': 'available',
            'storage_ref': {'bucket': 'private'},
        },
        {
            'event_type': 'artifact.rejected',
            'reservation_id': 'reservation-001',
            'logical_output_id': 'output-001',
            'reservation_state': 'rejected',
            'error': {'code': 'validation_failed', 'class': 'validation', 'retryable': False},
        },
    ],
)
def test_lifecycle_loader_rejects_incomplete_sensitive_and_invalid_error_payloads(
    payload: dict[str, object],
) -> None:
    """Keep lifecycle variants closed and failures value-free at their own boundary."""
    with pytest.raises(ValidationError):
        validate_artifact_lifecycle_event_payload(payload)


def test_event_rejects_lifecycle_discriminator_mismatch_but_keeps_generic_events_open() -> None:
    """Bind typed artifact payloads to Event.type without narrowing existing event payloads."""
    available = {
        'event_type': 'artifact.available',
        'artifact_id': 'artifact-001',
        'logical_output_id': 'output-001',
        'revision': 1,
        'custody': 'ordinary',
        'artifact_state': 'available',
    }

    with pytest.raises(ValidationError):
        validate_event(_event(available, 'artifact.expired'))
    with pytest.raises(PydanticValidationError):
        Event.model_validate(_event(available, 'artifact.expired'))
    generic = validate_event(_event({'unconstrained': {'still': 'supported'}}, 'planning'))
    assert generic.payload == {'unconstrained': {'still': 'supported'}}


def test_frozen_artifact_payload_dumps_as_plain_nested_python_containers() -> None:
    """Python-mode dumps thaw every nested frozen mapping back into plain dicts."""
    event = Event.model_validate(_event(_payloads()['artifact.failed'], 'artifact.failed'))

    dumped = cast('dict[str, object]', event.model_dump()['payload'])
    assert dumped == _payloads()['artifact.failed']
    assert type(dumped) is dict
    assert type(dumped['error']) is dict
