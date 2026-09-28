# pyright: strict
"""Golden validation tests for the canonical Flow graph schema."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from maivn_contracts.flows import load_flow_graph_schema, validate_flow_graph

FIXTURES_DIR = Path(__file__).resolve().parents[2] / 'fixtures'
MIN_NODES = 3
MAX_NODES = 256
MIN_EDGES = 2
MAX_EDGES = 512


def _fixtures(name: str) -> list[dict[str, Any]]:
    loaded = json.loads((FIXTURES_DIR / name).read_text(encoding='utf-8'))
    assert isinstance(loaded, list)
    return cast('list[dict[str, Any]]', loaded)


def test_flow_graph_schema_is_closed_and_bounded() -> None:
    """Publish the exact version, top-level keys, and graph bounds."""
    schema = load_flow_graph_schema()

    assert schema['$schema'] == 'https://json-schema.org/draft/2020-12/schema'
    assert schema['additionalProperties'] is False
    assert schema['required'] == ['schema_version', 'nodes', 'edges', 'layout']
    assert schema['properties']['schema_version']['const'] == 1
    assert schema['properties']['nodes']['minItems'] == MIN_NODES
    assert schema['properties']['nodes']['maxItems'] == MAX_NODES
    assert schema['properties']['edges']['minItems'] == MIN_EDGES
    assert schema['properties']['edges']['maxItems'] == MAX_EDGES
    assert schema['$defs']['layout']['properties']['node_positions']['maxProperties'] == MAX_NODES


@pytest.mark.parametrize('payload', _fixtures('valid_flow_graphs.json'))
def test_valid_flow_graph_fixtures_pass_json_schema_and_model(payload: dict[str, Any]) -> None:
    """Accept golden wire examples through both validation layers."""
    graph = validate_flow_graph(payload)

    assert graph.schema_version == 1


@pytest.mark.parametrize('payload', _fixtures('invalid_flow_graphs.json'))
def test_invalid_flow_graph_fixtures_fail_closed(payload: dict[str, Any]) -> None:
    """Reject invalid versions, selectors, roles, endpoints, and fields."""
    with pytest.raises((JsonSchemaValidationError, ValueError)):
        validate_flow_graph(payload)
