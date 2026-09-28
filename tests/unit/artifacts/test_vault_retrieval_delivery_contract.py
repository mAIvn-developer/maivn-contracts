"""Closed contract for one-shot retrieval-session credential delivery."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from pydantic import ValidationError

from maivn_contracts.artifacts import (
    VaultRetrievalSessionCredentialDelivery,
    vault_retrieval_session_credential_digest,
)

_SESSION_CREDENTIAL = 'c3ludGhldGljLXJldHJpZXZhbC1zZXNzaW9uLWNyZWRlbnRpYWw'
_SESSION_CREDENTIAL_DIGEST = vault_retrieval_session_credential_digest(_SESSION_CREDENTIAL)
_EXPIRES_AT = '2026-08-14T18:30:00Z'


def _delivery(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        'schema_version': 'vault-retrieval-session-credential-delivery-v1',
        'session_id': 'retrieval_session_01',
        'session_credential_digest': _SESSION_CREDENTIAL_DIGEST,
        'credential_delivery': 'delivered',
        'session_credential': _SESSION_CREDENTIAL,
        'expires_at': _EXPIRES_AT,
    }
    payload.update(overrides)
    return payload


def _validate_delivery(
    entrypoint: str,
    payload: dict[str, object],
) -> VaultRetrievalSessionCredentialDelivery:
    if entrypoint == 'constructor':
        return VaultRetrievalSessionCredentialDelivery(**cast('dict[str, Any]', payload))
    if entrypoint == 'model_validate':
        return VaultRetrievalSessionCredentialDelivery.model_validate(payload)
    return VaultRetrievalSessionCredentialDelivery.model_validate_json(json.dumps(payload))


def test_first_delivery_is_closed_and_serializes_the_direct_response_exactly() -> None:
    """A direct response may carry only the frozen fields and one credential."""
    delivery = VaultRetrievalSessionCredentialDelivery.model_validate(_delivery())

    assert delivery.model_dump(mode='json', exclude_none=True) == _delivery()
    assert json.loads(delivery.model_dump_json(exclude_none=True)) == _delivery()

    with pytest.raises(ValidationError):
        VaultRetrievalSessionCredentialDelivery.model_validate(
            _delivery(private_locator='forbidden'),
        )


@pytest.mark.parametrize(
    'payload',
    [
        _delivery(session_credential=None),
        _delivery(credential_delivery='not_replayable'),
    ],
)
def test_delivered_requires_the_raw_credential(payload: dict[str, object]) -> None:
    """A delivered claim without its credential would strand the approved caller."""
    with pytest.raises(ValidationError):
        VaultRetrievalSessionCredentialDelivery.model_validate(payload)


def test_not_replayable_is_stable_value_free_metadata() -> None:
    """A retry returns stable public metadata but cannot reconstruct the credential."""
    replay = VaultRetrievalSessionCredentialDelivery.model_validate(
        _delivery(
            credential_delivery='not_replayable',
            session_credential=None,
        ),
    )

    assert replay.model_dump(mode='json', exclude_none=True) == {
        'schema_version': 'vault-retrieval-session-credential-delivery-v1',
        'session_id': 'retrieval_session_01',
        'session_credential_digest': _SESSION_CREDENTIAL_DIGEST,
        'credential_delivery': 'not_replayable',
        'expires_at': _EXPIRES_AT,
    }
    assert 'session_credential' not in replay.model_dump(mode='json', exclude_none=True)


def test_not_replayable_refuses_any_raw_credential() -> None:
    """A replay branch must never become a second credential-delivery path."""
    with pytest.raises(ValidationError):
        VaultRetrievalSessionCredentialDelivery.model_validate(
            _delivery(credential_delivery='not_replayable'),
        )


def test_delivered_credential_matches_its_domain_separated_digest_value_free() -> None:
    """A raw credential cannot be paired with stable metadata for another session."""
    with pytest.raises(ValidationError) as caught:
        VaultRetrievalSessionCredentialDelivery.model_validate(
            _delivery(session_credential_digest='a' * 64),
        )

    rendered = f'{caught.value!s} {caught.value!r}'
    assert _SESSION_CREDENTIAL not in rendered
    assert _SESSION_CREDENTIAL not in repr(caught.value.errors())
    assert _SESSION_CREDENTIAL not in caught.value.json()
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_malformed_raw_credential_validation_is_value_free() -> None:
    """Pydantic diagnostics cannot retain a malformed raw capability value."""
    sentinel = 'private-retrieval-credential-sentinel!'

    with pytest.raises(ValidationError) as caught:
        VaultRetrievalSessionCredentialDelivery.model_validate(
            _delivery(session_credential=sentinel),
        )

    assert sentinel not in str(caught.value)
    assert sentinel not in repr(caught.value)
    assert sentinel not in repr(caught.value.errors())
    assert sentinel not in caught.value.json()
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize('entrypoint', ['constructor', 'model_validate', 'model_validate_json'])
@pytest.mark.parametrize('missing_field', ['schema_version', 'session_id', 'expires_at'])
def test_valid_raw_credential_is_value_free_when_other_delivery_fields_fail(
    missing_field: str,
    entrypoint: str,
) -> None:
    """Later public-field failures cannot make structured errors retain the capability."""
    payload = _delivery()
    del payload[missing_field]

    with pytest.raises(ValidationError) as caught:
        _validate_delivery(entrypoint, payload)

    assert _SESSION_CREDENTIAL not in str(caught.value)
    assert _SESSION_CREDENTIAL not in repr(caught.value)
    assert _SESSION_CREDENTIAL not in repr(caught.value.errors())
    assert _SESSION_CREDENTIAL not in caught.value.json()
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_raw_credential_never_renders_in_model_text() -> None:
    """Logging either model representation must not persist the capability."""
    delivery = VaultRetrievalSessionCredentialDelivery.model_validate(_delivery())

    assert _SESSION_CREDENTIAL not in repr(delivery)
    assert _SESSION_CREDENTIAL not in str(delivery)
    assert 'session_credential=' not in repr(delivery)
    assert 'session_credential=' not in str(delivery)


@pytest.mark.parametrize(
    'field',
    [
        'schema_version',
        'session_id',
        'session_credential_digest',
        'credential_delivery',
        'expires_at',
    ],
)
def test_every_frozen_delivery_field_is_required(field: str) -> None:
    """Omitting any public replay field would make retry state ambiguous."""
    payload = _delivery()
    del payload[field]

    with pytest.raises(ValidationError):
        VaultRetrievalSessionCredentialDelivery.model_validate(payload)
