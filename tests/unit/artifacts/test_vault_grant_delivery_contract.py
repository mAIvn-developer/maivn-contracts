"""Privacy boundary for one-shot grant credential delivery."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from pydantic import ValidationError

from maivn_contracts.artifacts import (
    VaultGrantCredentialDelivery,
    vault_grant_header_digest,
)

_GRANT_CREDENTIAL = 'Z3JhbnQtY3JlZGVudGlhbC1zZW50aW5lbC0wMDAx'
_GRANT_CREDENTIAL_DIGEST = vault_grant_header_digest(_GRANT_CREDENTIAL)


def _delivery(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        'intent_id': 'intent_0001',
        'state': 'executing_in_vault',
        'grant_credential_digest': _GRANT_CREDENTIAL_DIGEST,
        'credential_delivery': 'delivered',
        'grant_credential': _GRANT_CREDENTIAL,
        'expires_at': '2026-08-14T18:30:00Z',
    }
    payload.update(overrides)
    return payload


def _validate_delivery(
    entrypoint: str,
    payload: dict[str, object],
) -> VaultGrantCredentialDelivery:
    if entrypoint == 'constructor':
        return VaultGrantCredentialDelivery(**cast('dict[str, Any]', payload))
    if entrypoint == 'model_validate':
        return VaultGrantCredentialDelivery.model_validate(payload)
    return VaultGrantCredentialDelivery.model_validate_json(json.dumps(payload))


def _assert_value_free(error: ValidationError, sentinel: str) -> None:
    assert sentinel not in str(error)
    assert sentinel not in repr(error)
    assert sentinel not in repr(error.errors())
    assert sentinel not in error.json()
    assert error.__cause__ is None
    assert error.__context__ is None


def test_valid_grant_delivery_preserves_the_direct_wire_and_digest_binding() -> None:
    """A first delivery keeps its exact closed wire only when its digest matches."""
    delivery = VaultGrantCredentialDelivery.model_validate(_delivery())

    assert delivery.model_dump(mode='json', exclude_none=True) == _delivery()
    assert json.loads(delivery.model_dump_json(exclude_none=True)) == _delivery()
    assert _GRANT_CREDENTIAL not in repr(delivery)
    assert _GRANT_CREDENTIAL not in str(delivery)


@pytest.mark.parametrize('entrypoint', ['constructor', 'model_validate', 'model_validate_json'])
def test_malformed_grant_credential_is_absent_from_every_error_projection(
    entrypoint: str,
) -> None:
    """Malformed raw capabilities cannot survive any Pydantic diagnostic surface."""
    sentinel = 'private-grant-credential-sentinel!'

    with pytest.raises(ValidationError) as caught:
        _validate_delivery(entrypoint, _delivery(grant_credential=sentinel))

    _assert_value_free(caught.value, sentinel)


@pytest.mark.parametrize('entrypoint', ['constructor', 'model_validate', 'model_validate_json'])
def test_digest_mismatched_grant_credential_is_absent_from_every_error_projection(
    entrypoint: str,
) -> None:
    """A mismatched raw capability refuses without entering diagnostics."""
    with pytest.raises(ValidationError) as caught:
        _validate_delivery(entrypoint, _delivery(grant_credential_digest='a' * 64))

    _assert_value_free(caught.value, _GRANT_CREDENTIAL)


@pytest.mark.parametrize('entrypoint', ['constructor', 'model_validate', 'model_validate_json'])
@pytest.mark.parametrize('missing_field', ['intent_id', 'expires_at'])
def test_valid_grant_credential_is_absent_when_a_public_envelope_field_is_missing(
    entrypoint: str,
    missing_field: str,
) -> None:
    """Later public-field failures cannot retain an otherwise valid capability."""
    payload = _delivery()
    del payload[missing_field]

    with pytest.raises(ValidationError) as caught:
        _validate_delivery(entrypoint, payload)

    _assert_value_free(caught.value, _GRANT_CREDENTIAL)


def test_grant_delivery_replay_is_stable_and_cannot_reconstruct_the_credential() -> None:
    """A replay exposes only stable metadata and never rebuilds the raw grant."""
    replay_payload = _delivery(
        credential_delivery='not_replayable',
        grant_credential=None,
    )
    replay = VaultGrantCredentialDelivery.model_validate(replay_payload)

    assert replay.model_dump(mode='json', exclude_none=True) == {
        'intent_id': 'intent_0001',
        'state': 'executing_in_vault',
        'grant_credential_digest': _GRANT_CREDENTIAL_DIGEST,
        'credential_delivery': 'not_replayable',
        'expires_at': '2026-08-14T18:30:00Z',
    }
