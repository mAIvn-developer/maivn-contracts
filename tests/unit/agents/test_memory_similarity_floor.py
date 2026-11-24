"""An optional recall similarity floor rides the memory policy without changing old payloads."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from maivn_contracts.agents import AgentMemoryRetrievalPolicy, AgentVersion, validate_agent_version

_FIXTURE = Path(__file__).resolve().parents[2] / 'fixtures' / 'valid_agent_versions.json'


def _memory_version() -> dict[str, Any]:
    versions = cast('list[dict[str, Any]]', json.loads(_FIXTURE.read_text(encoding='utf-8')))
    return copy.deepcopy(next(version for version in versions if 'memory' in version))


def test_similarity_floor_roundtrips_through_schema_and_typed_version() -> None:
    """A caller-set floor is kept exactly, in the typed model and the JSON schema."""
    body = _memory_version()
    body['memory']['retrieval']['minimum_similarity'] = 0.35
    result = validate_agent_version(body)
    assert result.memory is not None
    assert result.memory.retrieval.minimum_similarity == pytest.approx(0.35)
    assert result.model_dump(mode='json', exclude_none=True)['memory'] == body['memory']


def test_an_unset_floor_is_absent_from_the_serialized_policy() -> None:
    """Omitted means the server default, and an older reader never sees the new key."""
    body = _memory_version()
    dumped = validate_agent_version(body).model_dump(mode='json', exclude_none=True)
    assert 'minimum_similarity' not in dumped['memory']['retrieval']


@pytest.mark.parametrize('bad_floor', [-0.1, 1.5, 'high'])
def test_similarity_floor_rejects_values_outside_zero_to_one(bad_floor: object) -> None:
    """The floor is a similarity between 0 and 1."""
    body = _memory_version()
    body['memory']['retrieval']['minimum_similarity'] = bad_floor
    with pytest.raises(ValidationError):
        AgentVersion.model_validate(body)
    with pytest.raises(SchemaValidationError):
        validate_agent_version(body)


def test_retrieval_policy_field_defaults_to_none() -> None:
    """The model default leaves the server's own floor in force."""
    assert AgentMemoryRetrievalPolicy.model_fields['minimum_similarity'].default is None
