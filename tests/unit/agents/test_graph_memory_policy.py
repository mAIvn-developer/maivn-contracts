"""Optional graph controls preserve immutable pre-graph agent versions."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from maivn_contracts.agents import AgentVersion, validate_agent_version

_FIXTURE = Path(__file__).resolve().parents[2] / 'fixtures' / 'valid_agent_versions.json'
_LEGACY_DIGEST = 'c1980bdf070306910e25e6e56a7b2d8cbea8a73e2d91c16ebb05b238f9b54ba8'


def _versions() -> list[dict[str, Any]]:
    return cast('list[dict[str, Any]]', json.loads(_FIXTURE.read_text(encoding='utf-8')))


def test_legacy_serialized_versions_retain_their_pre_change_digest() -> None:
    """No optional None field enters the canonical version payload used by registry callers."""
    encoded = json.dumps(
        [
            validate_agent_version(version).model_dump(mode='json', exclude_none=True)
            for version in _versions()
        ],
        sort_keys=True,
        separators=(',', ':'),
    )
    assert hashlib.sha256(encoded.encode()).hexdigest() == _LEGACY_DIGEST


def test_explicit_graph_policy_roundtrips_through_schema_and_typed_version() -> None:
    """A developer can independently select graph recall and bounded graph writes."""
    body = copy.deepcopy(next(version for version in _versions() if 'memory' in version))
    body['memory']['retrieval'].update({'graph_enabled': False, 'max_graph_assertions': 5})
    body['memory']['graph_extraction'] = {'enabled': True, 'max_count': 7}
    result = validate_agent_version(body)
    assert result.memory is not None
    assert result.memory.retrieval.graph_enabled is False
    assert result.model_dump(mode='json', exclude_none=True)['memory'] == body['memory']


@pytest.mark.parametrize('bad_count', [0, 17, True])
def test_graph_recall_bounds_reject_invalid_limits(bad_count: object) -> None:
    """Use the same1..16 strict count contract as existing recall categories."""
    body = copy.deepcopy(next(version for version in _versions() if 'memory' in version))
    body['memory']['retrieval']['max_graph_assertions'] = bad_count
    with pytest.raises(ValidationError):
        AgentVersion.model_validate(body)
    with pytest.raises(SchemaValidationError):
        validate_agent_version(body)
