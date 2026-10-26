# pyright: strict
"""Billable quantity rules: every way a usage unit is counted or refused."""

from __future__ import annotations

from typing import Any

import pytest

from maivn_contracts.events import Event, assemble_billing
from maivn_contracts.events import billing as billing_module
from maivn_contracts.events import load_projection as load_event_projection

USAGE_FIELDS = (
    'input_tokens',
    'output_tokens',
    'cache_read_input_tokens',
    'cache_creation_input_tokens',
)


def _event(event_type: str, payload: dict[str, Any], **lineage: str) -> Event:
    return Event.model_validate(
        {
            'event_id': 'evt-billing-1',
            'ordinal': 'producer-billing-000001',
            'type': event_type,
            'session_id': 'ses-billing',
            'root_event_id': 'evt-billing-root',
            'trigger_chain_depth': 0,
            'job_depth': 0,
            'job_index': 0,
            'actor': 'agent:billing-test',
            'mode': 'hosted',
            'payload': payload,
            'ts': '2026-07-15T12:00:01Z',
            **lineage,
        },
    )


def _quantities(event: Event) -> list[tuple[str, int]]:
    ledger = assemble_billing([event], org_id='org', project_id='project')
    return [(entry.unit_kind, entry.quantity) for entry in ledger.entries]


@pytest.mark.parametrize('event_type', ['final', 'error'])
def test_token_units_sum_present_usage_fields_and_treat_missing_ones_as_zero(
    event_type: str,
) -> None:
    """Terminal events bill the sum of whichever usage counters they carry."""
    assert _quantities(_event(event_type, {'usage': {'output_tokens': 9}})) == [('tokens', 9)]
    every = {field: index + 1 for index, field in enumerate(USAGE_FIELDS)}
    assert _quantities(_event(event_type, {'usage': every})) == [('tokens', 10)]


@pytest.mark.parametrize(
    'payload',
    [
        {},
        {'usage': 'not-a-mapping'},
        {'usage': {}},
        {'usage': {'input_tokens': 0, 'output_tokens': 0}},
        {'usage': {'input_tokens': 5, 'output_tokens': -1}},
        {'usage': {'input_tokens': 5, 'output_tokens': True}},
        {'usage': {'input_tokens': 5, 'output_tokens': 1.5}},
        {'usage': {'input_tokens': '5'}},
    ],
    ids=['no-usage', 'usage-text', 'empty', 'zero', 'negative', 'bool', 'float', 'string'],
)
def test_token_units_refuse_missing_zero_or_malformed_counters(payload: dict[str, Any]) -> None:
    """Absent usage, a zero total, or any non-integer or negative counter bills nothing."""
    assert _quantities(_event('final', payload)) == []


@pytest.mark.parametrize(
    ('payload', 'expected'),
    [
        ({'redaction_count': 3}, [('redaction', 3)]),
        ({'redaction_count': 0}, []),
        ({'redaction_count': -2}, []),
        ({'redaction_count': True}, []),
        ({'entity_count': 4}, []),
    ],
)
def test_redaction_units_use_the_exact_integer_count(
    payload: dict[str, Any],
    expected: list[tuple[str, int]],
) -> None:
    """Only a positive integer redaction count is billable."""
    assert _quantities(_event('message_redaction_applied', payload)) == expected


def test_fixed_units_bill_once_and_carry_the_full_lineage() -> None:
    """A fixed-quantity unit bills one and copies every lineage identifier."""
    ledger = assemble_billing(
        [
            _event(
                'assignment_received',
                {'private': 'never billed'},
                parent_session_id='ses-parent',
                trigger_id='trg-1',
                parent_trigger_id='trg-0',
                correlation_id='corr-1',
            ),
        ],
        org_id='org',
        project_id='project',
    )
    (entry,) = ledger.entries
    assert (entry.unit_kind, entry.quantity, entry.ts) == ('requests', 1, '2026-07-15T12:00:01Z')
    assert entry.lineage.model_dump() == {
        'org_id': 'org',
        'project_id': 'project',
        'session_id': 'ses-billing',
        'root_event_id': 'evt-billing-root',
        'parent_session_id': 'ses-parent',
        'trigger_id': 'trg-1',
        'parent_trigger_id': 'trg-0',
        'correlation_id': 'corr-1',
    }
    assert 'never billed' not in ledger.model_dump_json()


def _with_units(monkeypatch: pytest.MonkeyPatch, units: object) -> None:
    """Replace the shipped billing projection's `final` mapping with these units."""
    real = load_event_projection('billing')
    patched = {**real, 'mappings': {**real['mappings'], 'final': {'units': units}}}

    def load_projection(name: str) -> dict[str, Any]:
        del name
        return patched

    monkeypatch.setattr(billing_module, 'load_projection', load_projection)


@pytest.mark.parametrize(
    'units',
    [
        'not-a-list',
        {'unit_kind': 'tokens', 'quantity': 1},
        ['not-a-unit'],
        [{'quantity': 1}],
        [{'unit_kind': 7, 'quantity': 1}],
        [{'unit_kind': 'tokens', 'quantity': -1}],
        [{'unit_kind': 'tokens', 'quantity': True}],
        [{'unit_kind': 'tokens'}],
        [{'unit_kind': 'tokens', 'quantity_fields': 'usage.input_tokens'}],
        [{'unit_kind': 'tokens', 'quantity_fields': ['usage.input_tokens', 3]}],
    ],
    ids=[
        'units-not-list',
        'units-single-mapping',
        'unit-not-mapping',
        'no-kind',
        'kind-not-text',
        'negative-fixed',
        'bool-fixed',
        'no-quantity-rule',
        'fields-not-list',
        'field-not-text',
    ],
)
def test_malformed_projection_units_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    units: object,
) -> None:
    """A unit the projection document does not fully specify never bills anything."""
    _with_units(monkeypatch, units)
    assert _quantities(_event('final', {'usage': {'input_tokens': 5}})) == []


def test_projection_quantity_paths_walk_nested_mappings(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dotted quantity field reads a nested integer and stops at non-mappings."""
    _with_units(monkeypatch, [{'unit_kind': 'tokens', 'quantity_field': 'usage.input_tokens'}])
    assert _quantities(_event('final', {'usage': {'input_tokens': 5}})) == [('tokens', 5)]
    assert _quantities(_event('final', {'usage': 5})) == []
    assert _quantities(_event('final', {'usage': {'input_tokens': -5}})) == []


def test_projection_quantity_fields_must_be_a_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bare string of field names is not iterated character by character."""
    _with_units(monkeypatch, [{'unit_kind': 'tokens', 'quantity_fields': 'u'}])
    assert _quantities(_event('final', {'u': 5})) == []
