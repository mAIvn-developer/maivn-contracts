"""Typed preset selectors preserve legacy sources and reject incompatible events."""

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from maivn_contracts.scenarios import (
    ExternalConnectionEventSource,
    load_trigger_schema,
    matches_connection_selector,
    validate_trigger,
)


def source_payload(event_type: str, selector: object) -> dict[str, Any]:
    """Build a source without unrelated trigger defaults."""
    return {
        'kind': 'external_connection_event',
        'phase': 'phase_2',
        'connection_id': 'conn_shared',
        'event_type': event_type,
        'selector': selector,
    }


@pytest.mark.parametrize(
    ('event_type', 'selector'),
    [
        ('form.submitted', {'kind': 'form', 'form_id': 'contact'}),
        ('file.created', {'kind': 'local_file', 'watch_id': 'invoices'}),
        (
            'workflow_run.completed',
            {'kind': 'github', 'repository': 'owner/repo', 'conclusion': 'failure'},
        ),
    ],
)
def test_selector_roundtrip(event_type: str, selector: dict[str, str]) -> None:
    """Valid presets retain their discriminator and exact values on the wire."""
    payload = source_payload(event_type, selector)
    source = ExternalConnectionEventSource.model_validate(payload)
    assert source.model_dump(exclude_none=True) == payload
    schema = load_trigger_schema()['$defs']['externalConnectionEventSource']
    Draft202012Validator(schema).validate(payload)  # pyright: ignore[reportUnknownMemberType]
    assert (
        'selector'
        in ExternalConnectionEventSource.model_json_schema(mode='serialization')['properties']
    )


@pytest.mark.parametrize(
    ('event_type', 'selector'),
    [
        ('push', {'kind': 'form', 'form_id': 'contact'}),
        ('file.deleted', {'kind': 'local_file', 'watch_id': 'invoices'}),
        ('form.submitted', {'kind': 'github'}),
        ('issues.opened', {'kind': 'github', 'branch': 'main'}),
        ('push', {'kind': 'github', 'workflow': 'CI'}),
        ('pull_request.opened', {'kind': 'github', 'conclusion': 'success'}),
        ('push', {'kind': 'github', 'merged': True}),
        ('form.submitted', {'kind': 'form', 'form_id': 'a', 'unknown': 'x'}),
        ('form.submitted', {'kind': 'form', 'form_id': 1}),
        ('form.submitted', {'kind': 'form', 'form_id': '../bad'}),
        ('push', {'kind': 'github', 'repository': 'only-owner'}),
        ('pull_request.closed', {'kind': 'github', 'merged': 1}),
    ],
)
def test_invalid_selector_rejected_in_both_contracts(event_type: str, selector: object) -> None:
    """Provider-family mistakes cannot silently broaden matching."""
    payload = source_payload(event_type, selector)
    with pytest.raises(ValidationError):
        ExternalConnectionEventSource.model_validate(payload)
    assert not Draft202012Validator(
        load_trigger_schema()['$defs']['externalConnectionEventSource']
    ).is_valid(payload)  # pyright: ignore[reportUnknownMemberType]


def test_table_and_selector_are_exclusive() -> None:
    """A single external source cannot combine unrelated preset selectors."""
    payload = source_payload('form.submitted', {'kind': 'form', 'form_id': 'contact'})
    payload['table'] = 'public.orders'
    with pytest.raises(ValidationError):
        ExternalConnectionEventSource.model_validate(payload)
    assert not Draft202012Validator(
        load_trigger_schema()['$defs']['externalConnectionEventSource']
    ).is_valid(payload)  # pyright: ignore[reportUnknownMemberType]


def test_explicit_absent_selector_preserves_wire() -> None:
    """Null default selectors remain absent, including legacy database sources."""
    payload = source_payload('row.insert', None)
    payload['table'] = 'public.orders'
    source = ExternalConnectionEventSource.model_validate(payload)
    del payload['selector']
    assert source.model_dump() == payload


def test_shared_matching_corpus() -> None:
    """Every consumer can execute the same data-only matching vectors."""
    cases = json.loads(
        (Path(__file__).parents[2] / 'fixtures' / 'connection_selectors.json').read_text()
    )
    validator = Draft202012Validator(
        load_trigger_schema()['$defs']['externalConnectionEventSource']
    )
    for case in cases:
        source = ExternalConnectionEventSource.model_validate(
            source_payload(case['event_type'], case['selector'])
        )
        validator.validate(source.model_dump(exclude_none=True))  # pyright: ignore[reportUnknownMemberType]
        assert (
            matches_connection_selector(
                source.selector, case['incoming_event_type'], case['payload']
            )
            is case['matches']
        ), case['name']


def test_selectors_are_immutable() -> None:
    """A validated source cannot silently acquire different matching predicates."""
    source = ExternalConnectionEventSource.model_validate(
        source_payload('form.submitted', {'kind': 'form', 'form_id': 'contact'})
    )
    with pytest.raises(ValidationError, match='frozen_instance'):
        source.selector.form_id = 'billing'  # type: ignore[union-attr]


def test_two_forms_on_one_connection_select_only_the_intended_target() -> None:
    """The mandatory preset predicate prevents cross-form fanout."""
    sources = [
        ExternalConnectionEventSource.model_validate(
            source_payload('form.submitted', {'kind': 'form', 'form_id': form_id})
        )
        for form_id in ('contact', 'billing')
    ]
    assert [
        index
        for index, source in enumerate(sources)
        if matches_connection_selector(source.selector, 'form.submitted', {'form_id': 'contact'})
    ] == [0]


def test_user_filter_and_selector_survive_trigger_roundtrip() -> None:
    """The existing JSONPath filter remains independent of the preset selector."""
    payload = json.loads(
        (Path(__file__).parents[2] / 'fixtures' / 'valid_triggers.json').read_text()
    )[0]
    source = source_payload('form.submitted', {'kind': 'form', 'form_id': 'contact'})
    payload['source'] = source
    payload['filter'] = '$[?@.payload.fields.priority == "urgent"]'
    trigger = validate_trigger(payload)
    wire = trigger.model_dump(mode='json', exclude_none=True)
    assert wire['source'] == source
    assert wire['filter'] == payload['filter']
