"""Database selectors are schema-qualified without changing generic connection events."""

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from maivn_contracts.scenarios import ExternalConnectionEventSource, load_trigger_schema


def test_source_serialization_schema_retains_typed_fields() -> None:
    """A wire serializer must not erase the source's generated schema metadata."""
    schema = ExternalConnectionEventSource.model_json_schema(mode='serialization')
    assert schema['properties']['kind']['const'] == 'external_connection_event'
    assert 'connection_id' in schema['required']
    assert 'table' in schema['properties']


def test_generic_connection_source_preserves_legacy_wire_shape() -> None:
    """Adding a table selector must not emit a null property for existing sources."""
    payload = {
        'kind': 'external_connection_event',
        'phase': 'phase_2',
        'connection_id': 'conn-webhook',
        'event_type': 'webhook.received',
    }
    source = ExternalConnectionEventSource.model_validate(payload)
    assert source.model_dump() == payload
    assert source.model_dump(mode='json') == payload
    Draft202012Validator(load_trigger_schema()['$defs']['externalConnectionEventSource']).validate(  # pyright: ignore[reportUnknownMemberType]
        source.model_dump()
    )


def test_database_source_retains_exact_schema_qualified_table() -> None:
    """The source projection must retain the discriminator checked by both receivers."""
    source = ExternalConnectionEventSource.model_validate(
        {
            'kind': 'external_connection_event',
            'phase': 'phase_2',
            'connection_id': 'conn-db',
            'event_type': 'row.insert',
            'table': 'sales.orders',
        }
    )
    assert source.model_dump()['table'] == 'sales.orders'
    # jsonschema's validate signature does not declare its variadic keyword types.
    Draft202012Validator(load_trigger_schema()['$defs']['externalConnectionEventSource']).validate(  # pyright: ignore[reportUnknownMemberType]
        source.model_dump(exclude_none=True)
    )


@pytest.mark.parametrize(
    'table', ['orders', 'public.', '.orders', 'a.b.c', 'public.orders;drop', 'a.' + 'b' * 64]
)
def test_database_source_rejects_ambiguous_table_names(table: str) -> None:
    """A table selector names exactly one supported schema and identifier."""
    with pytest.raises(ValidationError):
        ExternalConnectionEventSource.model_validate(
            {
                'kind': 'external_connection_event',
                'phase': 'phase_2',
                'connection_id': 'conn-db',
                'event_type': 'row.insert',
                'table': table,
            }
        )
