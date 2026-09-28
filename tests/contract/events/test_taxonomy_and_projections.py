# pyright: strict
"""Contract tests for canonical event taxonomy and projection mapping tables."""

from __future__ import annotations

from typing import Any

from maivn_contracts.events import load_event_schema, load_projection, load_taxonomy


def _internal_types(taxonomy: dict[str, Any]) -> set[str]:
    internal = taxonomy['internal']
    event_types = set(internal['events'])
    for phase_group in internal['enrichment_phases'].values():
        event_types.update(phase_group)
    return event_types


def _all_canonical_types(taxonomy: dict[str, Any]) -> set[str]:
    return (
        _internal_types(taxonomy)
        | set(taxonomy['trigger']['events'])
        | set(taxonomy['data_plane']['events'])
        | set(taxonomy['connections']['events'])
        | set(taxonomy['artifacts']['events'])
        | set(taxonomy['projections']['canvas'])
    )


def test_event_schema_type_enum_matches_taxonomy_groups() -> None:
    """Keep the Event type enum aligned with taxonomy groups."""
    schema = load_event_schema()
    taxonomy = load_taxonomy()

    assert set(schema['properties']['type']['enum']) == _all_canonical_types(taxonomy)


def test_data_plane_trigger_bridge_events_are_canonical() -> None:
    """Pin the metadata-only memory and Storage bridge event vocabulary."""
    taxonomy = load_taxonomy()

    assert taxonomy['data_plane']['events'] == [
        'memory.record_changed',
        'storage.object_uploaded',
    ]


def test_canvas_projection_covers_every_internal_taxonomy_type() -> None:
    """Cover every internal taxonomy event in the canvas projection."""
    taxonomy = load_taxonomy()
    projection = load_projection('canvas')
    mappings = projection['mappings']

    assert projection['_meta']['lossy'] is True
    assert projection['_meta']['lossy_peers'] == ['trace']
    assert sorted(_internal_types(taxonomy) - set(mappings)) == []

    allowed_targets = set(taxonomy['projections']['canvas'])
    for mapping in mappings.values():
        if mapping.get('drop') is True:
            assert mapping['target'] is None
            assert mapping['drop_reason']
        else:
            assert mapping['target'] in allowed_targets


def test_trace_projection_is_curated_and_covers_every_canonical_type() -> None:
    """The user-facing trace projection maps every canonical type, with curation intact.

    Its loss is deliberate: the trace shows WHAT happened, never HOW the platform
    decides (owner ruling 2026-07-13). Every canonical event type must be either
    mapped to a trace aspect or explicitly dropped with a reason - a silently
    unmapped type would vanish from user traces without anyone deciding that.
    """
    taxonomy = load_taxonomy()
    schema = load_event_schema()
    projection = load_projection('trace')
    mappings = projection['mappings']

    assert projection['_meta']['lossy'] is True
    assert sorted(set(schema['properties']['type']['enum']) - set(mappings)) == []

    allowed_targets = set(taxonomy['projections']['trace'])
    for mapping in mappings.values():
        if mapping.get('drop') is True:
            assert mapping['target'] is None
            assert mapping['drop_reason']
        else:
            assert mapping['target'] in allowed_targets

    # The curation invariant: orchestration internals never get their own trace
    # vocabulary - processing phases collapse into the generalized working aspect.
    for phase in taxonomy['internal']['enrichment_phases']['processing']:
        assert mappings[phase]['target'] == 'trace.working'


def test_audit_projection_covers_every_canonical_type_with_explicit_curation() -> None:
    """Every canonical event is intentionally included or dropped from the audit log."""
    schema = load_event_schema()
    taxonomy = load_taxonomy()
    projection = load_projection('audit')
    mappings = projection['mappings']

    assert projection['_meta']['lossy'] is True
    assert sorted(set(schema['properties']['type']['enum']) - set(mappings)) == []

    allowed_targets = set(taxonomy['projections']['audit'])
    for mapping in mappings.values():
        if mapping.get('drop') is True:
            assert mapping['target'] is None
            assert mapping['drop_reason']
        else:
            assert mapping['target'] in allowed_targets
            assert mapping['payload_fields']


def test_billing_projection_covers_every_canonical_type_with_explicit_curation() -> None:
    """Every canonical event is intentionally included or dropped from billing."""
    schema = load_event_schema()
    taxonomy = load_taxonomy()
    projection = load_projection('billing')
    mappings = projection['mappings']

    assert projection['_meta']['lossy'] is True
    assert sorted(set(schema['properties']['type']['enum']) - set(mappings)) == []

    allowed_targets = set(taxonomy['projections']['billing'])
    for mapping in mappings.values():
        if mapping.get('drop') is True:
            assert mapping['target'] is None
            assert mapping['drop_reason']
        else:
            assert mapping['target'] in allowed_targets
            assert mapping['units']


def test_replay_projection_covers_every_canonical_type_with_explicit_curation() -> None:
    """Every canonical event is intentionally included or dropped from replay."""
    schema = load_event_schema()
    projection = load_projection('replay')
    mappings = projection['mappings']

    assert projection['_meta']['lossy'] is True
    assert sorted(set(schema['properties']['type']['enum']) - set(mappings)) == []

    allowed_targets = set(projection['target_events'])
    for mapping in mappings.values():
        if mapping.get('drop') is True:
            assert mapping['target'] is None
            assert mapping['drop_reason']
        else:
            assert mapping['target'] in allowed_targets
            assert mapping['curated_fields']


def test_webhook_projection_targets_existing_v1_webhook_vocabulary() -> None:
    """Target the existing v1 webhook event vocabulary."""
    taxonomy = load_taxonomy()
    projection = load_projection('webhook')

    assert projection['_meta']['lossy'] is False
    allowed_targets = set(taxonomy['projections']['webhook'])
    assert allowed_targets == {
        'session.started',
        'session.completed',
        'session.failed',
        'checkpoint.created',
        'checkpoint.resumed',
        'tool.executed',
        'tool.failed',
        'quota.warning',
        'quota.exceeded',
        'api_key.created',
        'api_key.rotated',
        'api_key.revoked',
    }

    for mapping in projection['mappings'].values():
        assert mapping['target'] in allowed_targets
