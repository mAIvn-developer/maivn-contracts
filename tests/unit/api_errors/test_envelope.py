"""The shared error envelope: canonical bytes, validation paths, and shape checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import BaseModel, ValidationError

from maivn_contracts.api_errors import (
    ApiErrorBody,
    ApiErrorField,
    coerce_code,
    default_error,
    error_body,
    is_error_body,
    public_field_path,
    render_error_body,
    validation_fields,
)

_VECTORS = Path(__file__).resolve().parents[2] / 'fixtures' / 'api_error_vectors.json'


def _cases() -> list[dict[str, Any]]:
    document = cast('dict[str, Any]', json.loads(_VECTORS.read_text(encoding='utf-8')))
    return cast('list[dict[str, Any]]', document['cases'])


@pytest.mark.parametrize('case', _cases(), ids=lambda case: str(case['name']))
def test_every_vector_renders_to_its_exact_bytes(case: dict[str, Any]) -> None:
    """Each vector renders to the pinned bytes and reads back as an envelope."""
    body = error_body(**case['error'])
    assert render_error_body(body) == case['body'].encode('utf-8')
    assert is_error_body(json.loads(case['body']))


@pytest.mark.parametrize('case', _cases(), ids=lambda case: str(case['name']))
def test_the_typed_model_renders_the_same_bytes(case: dict[str, Any]) -> None:
    """The typed model and the dict builder agree byte for byte."""
    model = ApiErrorBody.model_validate_json(case['body'])
    assert render_error_body(model.to_json_dict()) == case['body'].encode('utf-8')


def test_detail_and_code_come_first_and_empty_members_are_omitted() -> None:
    """Empty optional members never appear."""
    body = error_body(code='conflict', detail='Busy.', fields=(), context={})
    assert list(body) == ['detail', 'code']


@pytest.mark.parametrize(
    'value',
    [
        {'detail': 'Not Found'},
        {'code': 'x', 'reason': 'y'},
        {'error': {'code': 'not_found', 'message': 'resource not found', 'details': []}},
        {'detail': [{'loc': ['body'], 'msg': 'Field required', 'type': 'missing'}]},
        {'detail': 'x', 'code': 'Not A Code'},
        {'code': 'not_found', 'detail': 'Not found.'},
        {'detail': 'x', 'code': 'x', 'extra': 1},
        {'detail': 'x', 'code': 'x', 'fields': [{'loc': ['a'], 'msg': 'm'}]},
        ['detail', 'code'],
        'Not found',
    ],
)
def test_anything_else_is_not_an_error_body(value: object) -> None:
    """Every older shape and every near miss is refused."""
    assert not is_error_body(value)


def test_codes_must_be_machine_codes() -> None:
    """Free text never becomes a code, and a message is never empty."""
    with pytest.raises(ValueError, match='error code'):
        error_body(code='Not Found', detail='x')
    with pytest.raises(ValueError, match='detail'):
        error_body(code='not_found', detail='')


def test_every_status_has_a_generic_answer() -> None:
    """Unknown statuses fall back to their class."""
    assert default_error(404) == ('not_found', 'Not found.')
    assert default_error(422) == ('validation_failed', 'Request validation failed.')
    assert default_error(418)[0] == 'bad_request'
    assert default_error(599)[0] == 'internal_error'


class _Leaf(BaseModel):
    count: int


class _Holder(BaseModel):
    items: list[_Leaf | int]
    name: str


def test_validation_fields_keep_the_callers_path_and_nothing_internal() -> None:
    """Model names and input values never reach a validation reply."""
    with pytest.raises(ValidationError) as caught:
        _Holder.model_validate({'items': [{'count': 'many'}], 'secret_value': 1})
    fields = validation_fields(caught.value.errors())
    paths = {field.field for field in fields}
    assert 'items.0.count' in paths
    assert 'name' in paths
    rendered = json.dumps([field.model_dump() for field in fields])
    assert '_Leaf' not in rendered
    assert 'many' not in rendered


def test_public_field_paths_drop_framework_and_model_segments() -> None:
    """Only the caller-written path survives."""
    assert public_field_path(('body', 'messages', 0, 'content')) == 'messages.0.content'
    assert public_field_path(('query', 'limit')) == 'query.limit'
    assert public_field_path(('body', 'function-after[_check(), Scenario]', 'nodes')) == 'nodes'
    assert public_field_path(('body', 'ScenarioDocument', 'title')) == 'title'
    assert public_field_path(('body',)) == ''


def test_validation_fields_skip_entries_without_a_message() -> None:
    """Entries without a message are dropped."""
    fields = validation_fields([{'loc': ('body', 'a')}, {'loc': ('body', 'b'), 'msg': 'bad'}])
    assert fields == (ApiErrorField(field='b', message='bad'),)


def test_runtime_codes_are_folded_or_replaced_never_trusted() -> None:
    """A dotted or spaced code folds to snake case; nothing usable falls back."""
    assert coerce_code('flow.cycle-detected', 422) == 'flow_cycle_detected'
    assert coerce_code('not_found', 404) == 'not_found'
    assert coerce_code('!!!', 409) == 'conflict'
    assert coerce_code(None, 503) == 'service_unavailable'
    assert coerce_code('9lives', 400) == 'bad_request'
