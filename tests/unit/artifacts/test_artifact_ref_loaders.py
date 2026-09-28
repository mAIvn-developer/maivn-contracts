# pyright: strict
"""Unit tests for ArtifactRef schema loading and closed-custody validation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema.exceptions import ValidationError
from pydantic import ValidationError as PydanticValidationError

from maivn_contracts.artifacts import (
    OrdinaryArtifactRef,
    PrivateArtifactRef,
    load_artifact_ref_schema,
    validate_artifact_ref,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / 'fixtures'
ARTIFACT_REF_FIXTURE_COUNT = 2
CANONICAL_UTC_TIMESTAMP_PATTERN = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$'


def _load_fixture(name: str) -> list[dict[str, Any]]:
    loaded = json.loads((FIXTURES_DIR / name).read_text(encoding='utf-8'))
    assert isinstance(loaded, list)
    return cast('list[dict[str, Any]]', loaded)


def test_artifact_ref_schema_has_closed_discriminated_custody_variants() -> None:
    """Removing a variant closure would admit cross-custody metadata leakage."""
    schema = load_artifact_ref_schema()

    assert schema['additionalProperties'] is False
    assert schema['discriminator'] == {'propertyName': 'custody'}
    assert set(schema['$defs']) >= {
        'ordinaryArtifactRef',
        'privateArtifactRef',
        'effectiveRetention',
        'producerLineage',
        'validationReceipt',
        'retrievalAction',
    }
    assert schema['$defs']['ordinaryArtifactRef']['additionalProperties'] is False
    assert schema['$defs']['privateArtifactRef']['additionalProperties'] is False
    for definition in schema['$defs'].values():
        if definition.get('type') == 'object':
            assert definition['additionalProperties'] is False


def test_artifact_ref_schema_pins_ids_mime_states_and_relations() -> None:
    """Broadening a public token, MIME, state, or relation would weaken the wire contract."""
    schema = load_artifact_ref_schema()
    defs = schema['$defs']

    assert defs['tokenId']['pattern'] == r'^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$'
    assert set(defs['mimeType']['enum']) == {
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/octet-stream',
        'audio/mpeg',
        'audio/wav',
        'image/jpeg',
        'image/png',
    }
    assert set(defs['ordinaryArtifactState']['enum']) == {
        'available',
        'expired',
        'deleting',
        'deleted',
        'delete_incomplete',
    }
    assert set(defs['privateArtifactState']['enum']) == {
        'available_in_vault',
        'expired',
        'deleting',
        'deletion_pending_backup_expiry',
        'deleted',
        'delete_incomplete',
    }
    assert set(defs['retrievalAction']['properties']['relation']['enum']) == {
        'artifact.download_authorization',
        'artifact.vault_download_authorization',
    }
    assert (
        defs['ordinaryArtifactRef']['properties']['retrieval_action']['allOf'][1]['properties'][
            'relation'
        ]['const']
        == 'artifact.download_authorization'
    )
    assert (
        defs['privateArtifactRef']['properties']['retrieval_action']['allOf'][1]['properties'][
            'relation'
        ]['const']
        == 'artifact.vault_download_authorization'
    )
    assert set(defs['producerLineage']['properties']['producer_class']['enum']) == {
        'hosted_tool',
        'external_tool',
        'provider',
        'delegated_agent',
        'swarm_member',
        'rework',
        'vault',
    }
    assert defs['rfc3339UtcTimestamp']['pattern'] == CANONICAL_UTC_TIMESTAMP_PATTERN
    assert defs['ordinaryArtifactRef']['properties']['created_at'] == {
        '$ref': '#/$defs/rfc3339UtcTimestamp',
    }
    assert defs['effectiveRetention']['properties']['expires_at'] == {
        '$ref': '#/$defs/rfc3339UtcTimestamp',
    }


def test_schema_and_models_accept_exact_presentation_references() -> None:
    """PPTX create/rework outcomes must survive every public contract lane."""
    ordinary, private = deepcopy(_load_fixture('valid_artifact_refs.json'))
    pptx = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    ordinary.update(
        {
            'kind': 'presentation',
            'mime_type': pptx,
            'display_filename': 'deck.pptx',
            'safe_preview': {'kind': 'presentation', 'slide_count': 4},
        },
    )
    private.update(
        {
            'kind': 'presentation',
            'mime_type': pptx,
            'display_label': 'Private presentation',
        },
    )

    assert validate_artifact_ref(ordinary).kind == 'presentation'
    private_reference = validate_artifact_ref(private)
    assert isinstance(private_reference, PrivateArtifactRef)
    assert private_reference.display_label == 'Private presentation'
    assert OrdinaryArtifactRef.model_validate(ordinary).safe_preview is not None
    assert PrivateArtifactRef.model_validate(private).mime_type == pptx


def test_artifact_ref_validators_round_trip_all_valid_fixtures() -> None:
    """Removing a required custody-safe field would reject a canonical ref."""
    fixtures = _load_fixture('valid_artifact_refs.json')

    assert len(fixtures) == ARTIFACT_REF_FIXTURE_COUNT
    first_dump = validate_artifact_ref(fixtures[0]).model_dump(mode='json', exclude_none=True)
    second_dump = validate_artifact_ref(fixtures[1]).model_dump(mode='json', exclude_none=True)
    assert first_dump == fixtures[0]
    assert second_dump == fixtures[1]


@pytest.mark.parametrize('fixture', _load_fixture('invalid_artifact_refs.json'))
def test_artifact_ref_validator_rejects_forbidden_or_inconsistent_wire_shapes(
    fixture: dict[str, Any],
) -> None:
    """Wrong custody, revision, MIME, or URL-like fields must fail closed."""
    with pytest.raises(ValidationError):
        validate_artifact_ref(fixture)


def test_invalid_fixtures_each_isolate_one_named_violation() -> None:
    """Repairing the intended mutation must make every negative fixture valid."""
    invalid = _load_fixture('invalid_artifact_refs.json')
    repaired = deepcopy(invalid)

    repaired[0].pop('sha256')
    repaired[1].pop('supersedes_artifact_id')
    repaired[2]['supersedes_artifact_id'] = 'art_ordinary_0000'
    repaired[3]['mime_type'] = 'application/pdf'
    repaired[4]['display_filename'] = 'report.pdf'

    for fixture in invalid:
        assert 'expires_at' in fixture['effective_retention']
    for fixture in repaired:
        validate_artifact_ref(fixture)


def test_direct_models_enforce_revision_and_custody_state_invariants() -> None:
    """Bypassing a loader must not allow a stale or cross-custody model."""
    ordinary, private = _load_fixture('valid_artifact_refs.json')
    stale_revision = dict(ordinary)
    stale_revision['revision'] = 2
    private_state = dict(private)
    private_state['state'] = 'available'

    with pytest.raises(PydanticValidationError):
        OrdinaryArtifactRef.model_validate(stale_revision)
    with pytest.raises(PydanticValidationError):
        PrivateArtifactRef.model_validate(private_state)


@pytest.mark.parametrize(
    'timestamp',
    ['2026-08-09t00:00:00z', '2026-08-09T00:00:00+00:00'],
)
def test_schema_and_direct_models_reject_noncanonical_timestamps(timestamp: str) -> None:
    """Wire and direct validation must agree on the canonical UTC-Z timestamp grammar."""
    fixture = deepcopy(_load_fixture('valid_artifact_refs.json')[0])
    fixture['created_at'] = timestamp
    with pytest.raises(ValidationError):
        validate_artifact_ref(fixture)
    with pytest.raises(PydanticValidationError):
        OrdinaryArtifactRef.model_validate(fixture)


def test_timestamp_projection_preserves_the_exact_wire_string() -> None:
    """A canonical timestamp must not normalize into a different serialized spelling."""
    fixture = _load_fixture('valid_artifact_refs.json')[0]
    model = OrdinaryArtifactRef.model_validate(fixture)

    assert model.created_at == fixture['created_at']
    assert model.effective_retention.expires_at == fixture['effective_retention']['expires_at']
    assert isinstance(model.created_at, str)
    assert OrdinaryArtifactRef.model_json_schema()['properties']['created_at']['pattern'] == (
        CANONICAL_UTC_TIMESTAMP_PATTERN
    )


@pytest.mark.parametrize(
    ('field_name', 'value'),
    [
        ('validator_profile', 'https://vault.example/profile'),
        ('validator_profile', 'profiles/document'),
        ('validator_profile', 'private customer profile'),
        ('validator_version', 'https://vault.example/version'),
        ('validator_version', 'versions/1.0.0'),
        ('validator_version', 'private customer version'),
    ],
)
def test_schema_and_direct_models_reject_non_identifier_validation_receipts(
    field_name: str,
    value: str,
) -> None:
    """Receipt profile/version fields must remain bounded value-free identifiers."""
    fixture = deepcopy(_load_fixture('valid_artifact_refs.json')[0])
    fixture['validation_receipt'][field_name] = value

    with pytest.raises(ValidationError):
        validate_artifact_ref(fixture)
    with pytest.raises(PydanticValidationError):
        OrdinaryArtifactRef.model_validate(fixture)


@pytest.mark.parametrize(
    ('fixture_index', 'changes'),
    [
        (0, {'artifact_id': 'bad id'}),
        (0, {'revision': True}),
        (0, {'created_at': '2026-08-09'}),
        (0, {'size_bytes': True}),
        (0, {'size_bytes': 0}),
        (0, {'sha256': 'A' * 64}),
        (0, {'display_filename': '../report.pdf'}),
        (0, {'mime_type': 'image/png'}),
        (0, {'safe_preview': {'kind': 'document', 'page_count': 501}}),
        (0, {'safe_preview': {'kind': 'image', 'width_pixels': 10, 'height_pixels': 10}}),
        (0, {'retrieval_action': {'relation': 'artifact.download_authorization', 'href': '/x'}}),
        (
            0,
            {
                'producer': {
                    'producer_class': 'import',
                    'producer_id': 'producer_0001',
                    'root_invocation_id': 'invocation_0001',
                },
            },
        ),
        (1, {'display_label': 'Private document'}),
        (1, {'deletion_receipt_id': 'receipt_delete_0001'}),
        (1, {'creation_receipt_id': 'bad id'}),
        (1, {'size_bytes': 20}),
        (
            1,
            {
                'producer': {
                    'producer_class': 'provider',
                    'producer_id': 'provider_file_123',
                    'root_invocation_id': 'invocation_0001',
                },
            },
        ),
    ],
)
def test_direct_models_reject_strict_or_cross_field_violations(
    fixture_index: int,
    changes: dict[str, Any],
) -> None:
    """Weakening strict values or cross-field checks would admit ambiguous references."""
    fixture = deepcopy(_load_fixture('valid_artifact_refs.json')[fixture_index])
    fixture.update(changes)
    model = OrdinaryArtifactRef if fixture_index == 0 else PrivateArtifactRef

    with pytest.raises(PydanticValidationError):
        model.model_validate(fixture)


@pytest.mark.parametrize(
    ('field_name', 'value'),
    [
        ('display_filename', 'private.docx'),
        ('safe_preview', {'kind': 'image', 'width_pixels': 1, 'height_pixels': 1}),
        ('locator', 'vault/private/file'),
        ('namespace', 'tenant-private'),
        ('storage_ref', {'bucket': 'private', 'path': 'file'}),
        ('provider_id', 'provider_file_123'),
        ('signed_url', 'https://vault.example/private'),
        ('capability_token', 'private_capability'),
        ('grant_id', 'private_grant'),
        ('hydrated_metadata', {'title': 'private customer title'}),
    ],
)
def test_private_refs_structurally_forbid_sensitive_or_resolvable_fields(
    field_name: str,
    value: object,
) -> None:
    """Private refs must remain value-free and contain only the vault-issued handle."""
    fixture = deepcopy(_load_fixture('valid_artifact_refs.json')[1])
    fixture[field_name] = value

    with pytest.raises(ValidationError):
        validate_artifact_ref(fixture)
    with pytest.raises(PydanticValidationError):
        PrivateArtifactRef.model_validate(fixture)


@pytest.mark.parametrize(
    ('kind', 'mime_type', 'safe_preview'),
    [
        (
            'document',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            {'kind': 'document', 'page_count': 1},
        ),
        (
            'spreadsheet',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            {'kind': 'spreadsheet', 'sheet_count': 100},
        ),
        ('image', 'image/jpeg', {'kind': 'image', 'width_pixels': 8000, 'height_pixels': 5000}),
        ('audio', 'audio/wav', {'kind': 'audio', 'duration_seconds': 7200}),
        ('other', 'application/octet-stream', None),
    ],
)
def test_kind_mime_and_safe_preview_variants_validate_together(
    kind: str,
    mime_type: str,
    safe_preview: dict[str, Any] | None,
) -> None:
    """Each allowlisted MIME and preview variant must agree with its artifact kind."""
    fixture = deepcopy(_load_fixture('valid_artifact_refs.json')[0])
    fixture['kind'] = kind
    fixture['mime_type'] = mime_type
    if safe_preview is None:
        fixture.pop('safe_preview', None)
    else:
        fixture['safe_preview'] = safe_preview

    assert validate_artifact_ref(fixture).model_dump(mode='json', exclude_none=True) == fixture


def test_image_preview_axis_bounds_have_schema_and_projection_parity() -> None:
    """The public projection must not add an aggregate pixel rule absent from JSON Schema."""
    fixture = deepcopy(_load_fixture('valid_artifact_refs.json')[0])
    fixture['kind'] = 'image'
    fixture['mime_type'] = 'image/png'
    fixture['safe_preview'] = {
        'kind': 'image',
        'width_pixels': 40_000_000,
        'height_pixels': 40_000_000,
    }

    assert validate_artifact_ref(fixture).model_dump(mode='json', exclude_none=True) == fixture


@pytest.mark.parametrize(
    ('state', 'has_deletion_receipt'),
    [
        ('available_in_vault', False),
        ('expired', False),
        ('deleting', True),
        ('deletion_pending_backup_expiry', True),
        ('deleted', True),
        ('delete_incomplete', True),
    ],
)
def test_private_deletion_receipt_tracks_public_state(
    state: str,
    has_deletion_receipt: bool,  # noqa: FBT001
) -> None:
    """Private deletion evidence must appear exactly in deletion lifecycle states."""
    fixture = deepcopy(_load_fixture('valid_artifact_refs.json')[1])
    fixture['state'] = state
    if has_deletion_receipt:
        fixture['deletion_receipt_id'] = 'receipt_delete_0001'

    assert validate_artifact_ref(fixture).model_dump(mode='json', exclude_none=True) == fixture
