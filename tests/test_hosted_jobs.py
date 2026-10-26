"""Job opt-in bounds must be explicit, strict and finite."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from maivn_contracts.jobs import HostedJobOptions, HostedJobStatus


@pytest.mark.parametrize(
    'changes',
    [
        {'max_steps': 0},
        {'max_steps': True},
        {'max_steps': 1.5},
        {'max_duration_seconds': 0},
        {'max_duration_seconds': float('inf')},
        {'max_duration_seconds': float('nan')},
        {'max_duration_seconds': True},
        {'max_duration_seconds': 1801},
        {'idempotency_key': ' '},
    ],
)
def test_job_bounds_refuse_invalid_values(changes: dict[str, object]) -> None:
    """Exercise test job bounds refuse invalid values."""
    with pytest.raises(ValidationError):
        HostedJobOptions.model_validate(
            {'idempotency_key': 'job-1', 'max_steps': 4, 'max_duration_seconds': 30, **changes}
        )


@pytest.mark.parametrize('field', ['idempotency_key', 'max_steps', 'max_duration_seconds'])
def test_job_bounds_have_no_implicit_defaults(field: str) -> None:
    """Exercise test job bounds have no implicit defaults."""
    payload = {'idempotency_key': 'job-1', 'max_steps': 4, 'max_duration_seconds': 30}
    payload.pop(field)
    with pytest.raises(ValidationError):
        HostedJobOptions.model_validate(payload)


@pytest.mark.parametrize(
    ('model', 'name'),
    [(HostedJobOptions, 'hosted_job_options'), (HostedJobStatus, 'hosted_job_status')],
)
def test_generated_runtime_binding_schema_matches_model(
    model: type[HostedJobOptions] | type[HostedJobStatus], name: str
) -> None:
    """The shared TS/Go generator input remains the canonical Python job model schema."""
    schema = json.loads(
        (Path(__file__).resolve().parents[1] / 'runtime' / f'{name}.schema.json').read_text()
    )
    schema.pop('$schema')
    schema.pop('$id')
    assert schema == model.model_json_schema()


@pytest.mark.parametrize(
    ('model', 'name'),
    [(HostedJobOptions, 'hosted_job_options'), (HostedJobStatus, 'hosted_job_status')],
)
def test_shared_binding_fixtures_agree_with_python(
    model: type[HostedJobOptions] | type[HostedJobStatus], name: str
) -> None:
    """Valid and invalid Go/TS input fixtures reflect the same canonical job models."""
    folder = Path(__file__).resolve().parent / 'fixtures'
    for value in json.loads((folder / f'valid_{name}.json').read_text()):
        model.model_validate(value)
    for value in json.loads((folder / f'invalid_{name}.json').read_text()):
        with pytest.raises(ValidationError):
            model.model_validate(value)
