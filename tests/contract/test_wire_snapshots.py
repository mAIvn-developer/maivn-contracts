# pyright: strict
"""Pin the wire contract of every model: JSON schemas, serialization and validation errors.

The JSON Lines files under ``tests/snapshots`` are the reference (see its README):

* ``schemas/_defs.jsonl``: every ``$defs`` entry any schema below uses, one per line,
  shared across models and subpackages.
* ``schemas/<subpackage>.jsonl``: one line per model class and per exported alias or
  constant, holding ``model_json_schema()`` in validation and serialization mode with its
  ``$defs`` moved to the shared file. A schema whose body equals its own shared entry is
  written ``=def``; a ``$defs`` list is written only when it is not the sorted closure of
  the body's references (which is what pydantic emits).
* ``instances/<subpackage>.jsonl``: one line per model with representative inputs, each
  with its verdict and a digest of everything it produced: ``model_dump_json()`` (plain
  and ``by_alias=True, exclude_none=True``), the Python-mode ``model_dump()`` whenever its
  value types differ from the JSON form, or the full ``ValidationError.errors()`` list.

Keys keep pydantic's own order, so a reordered schema or dump is a change too. A refactor
must leave every file byte-identical. Regenerate only for an approved contract change, then
review the diff: ``MAIVN_CONTRACTS_UPDATE_SNAPSHOTS=1 uv run pytest
tests/contract/test_wire_snapshots.py``. Update mode recomputes the schemas and the outputs
of the inputs already recorded; it never invents inputs.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import os
import pkgutil
import re
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

import maivn_contracts

if TYPE_CHECKING:
    from types import ModuleType

SNAPSHOTS = Path(__file__).resolve().parents[1] / 'snapshots'
UPDATE = os.environ.get('MAIVN_CONTRACTS_UPDATE_SNAPSHOTS') == '1'
SAME_AS_VALIDATION = '<same as validation>'
OWN_DEF = '=def'
REF_PREFIX = '#/$defs/'
SUBPACKAGES = sorted(
    info.name
    for info in pkgutil.iter_modules(maivn_contracts.__path__)
    if not info.name.startswith('_')
)
Json = dict[str, Any]


def _modules(subpackage: str) -> list[ModuleType]:
    package = importlib.import_module(f'maivn_contracts.{subpackage}')
    return [
        package,
        *(
            importlib.import_module(info.name)
            for info in pkgutil.walk_packages(package.__path__, f'{package.__name__}.')
        ),
    ]


@cache
def _models(subpackage: str) -> dict[str, type[BaseModel]]:
    """Every model class defined in the subpackage, keyed by its (unique) qualified name.

    Keys are class names, not module paths, so moving a class between modules of the same
    subpackage leaves the snapshot unchanged. Parametrized generics are skipped: their
    schemas appear inside the models that use them.
    """
    found: dict[str, type[BaseModel]] = {}
    for module in _modules(subpackage):
        for value in vars(module).values():
            if (
                inspect.isclass(value)
                and issubclass(value, BaseModel)
                and value.__module__ == module.__name__
                and '[' not in value.__qualname__
            ):
                assert found.setdefault(value.__qualname__, value) is value
    return dict(sorted(found.items()))


def _references(value: object, found: set[str]) -> set[str]:
    if isinstance(value, Mapping):
        for key, item in cast('Mapping[str, object]', value).items():
            if key == '$ref' and isinstance(item, str) and item.startswith(REF_PREFIX):
                found.add(item[len(REF_PREFIX) :])
            else:
                _references(item, found)
    elif isinstance(value, list):
        for item in cast('list[object]', value):
            _references(item, found)
    return found


def _sorted_closure(body: Json, definitions: Json) -> list[str]:
    reached: set[str] = set()
    pending = list(_references(body, set()))
    while pending:
        name = pending.pop()
        if name not in reached and name in definitions:
            reached.add(name)
            pending.extend(_references(definitions[name], set()))
    return sorted(reached)


class _SchemaTable:
    """Split schemas into one shared ``$defs`` table plus compact per-owner entries."""

    def __init__(self) -> None:
        self.definitions: Json = {}

    def entry(self, owner: str, schema: object) -> object:
        if not isinstance(schema, dict):
            return schema
        body = dict(cast('Json', schema))
        definitions = cast('Json', body.pop('$defs', {}))
        for name, definition in definitions.items():
            known = self.definitions.setdefault(name, definition)
            assert known == definition, f'$defs entry {name!r} differs between schemas'
        compact: Json = {}
        if list(definitions) != _sorted_closure(body, definitions):
            compact['defs'] = list(definitions)
        compact['schema'] = OWN_DEF if self.definitions.get(owner) == body else body
        return compact

    def pair(self, owner: str, validation: Json, serialization: Json) -> Json:
        return {
            'validation': self.entry(owner, validation),
            'serialization': (
                SAME_AS_VALIDATION
                if serialization == validation
                else self.entry(owner, serialization)
            ),
        }


def _export_entry(table: _SchemaTable, name: str, value: object) -> object:
    if isinstance(value, (str, int)):
        return {'value': value}
    if isinstance(value, frozenset):
        return {'frozenset': sorted(cast('frozenset[str]', value))}
    if isinstance(value, re.Pattern):
        pattern = cast('re.Pattern[str]', value)
        return {'pattern': pattern.pattern, 'flags': int(pattern.flags)}
    adapter: TypeAdapter[Any] = TypeAdapter(value)
    return table.pair(
        name,
        adapter.json_schema(mode='validation'),
        adapter.json_schema(mode='serialization'),
    )


@cache
def _schema_lines() -> dict[str, tuple[str, ...]]:
    """Render the lines of every snapshot schema file, keyed by file stem."""
    table = _SchemaTable()
    lines: dict[str, tuple[str, ...]] = {}
    for subpackage in SUBPACKAGES:
        rows: list[str] = []
        for name, model in _models(subpackage).items():
            pair = table.pair(
                name,
                model.model_json_schema(mode='validation'),
                model.model_json_schema(mode='serialization'),
            )
            rows.append(_line(['model', name, pair]))
        package = importlib.import_module(f'maivn_contracts.{subpackage}')
        for name in sorted(cast('list[str]', getattr(package, '__all__', []))):
            value = getattr(package, name)
            if not (inspect.isclass(value) or inspect.isroutine(value) or inspect.ismodule(value)):
                rows.append(_line(['export', name, _export_entry(table, name, value)]))
        lines[subpackage] = tuple(rows)
    lines['_defs'] = tuple(
        _line([name, definition]) for name, definition in sorted(table.definitions.items())
    )
    return lines


def _line(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _python_shape(value: object) -> object:
    """Render a Python-mode dump as JSON, tagging every value type JSON cannot carry."""
    if value is None or type(value) in {str, int, float, bool}:
        return value
    value_type: type[object] = type(value)
    shape: object
    if isinstance(value, Mapping):
        mapping = cast('Mapping[str, object]', value)
        shape = {key: _python_shape(item) for key, item in mapping.items()}
    elif isinstance(value, (list, tuple)):
        shape = [_python_shape(item) for item in cast('tuple[object, ...]', value)]
    elif isinstance(value, (set, frozenset)):
        shape = sorted(repr(item) for item in cast('set[object]', value))
    else:
        shape = repr(value)
    return shape if value_type in {dict, list} else {f'<{value_type.__qualname__}>': shape}


def _observe(model: type[BaseModel], mode: str, payload: object) -> tuple[str, Json]:
    """Validate one recorded input and return its verdict and everything it produced."""
    try:
        if mode == 'json':
            instance = model.model_validate_json(cast('str', payload))
        else:
            instance = model.model_validate(payload)
    except ValidationError as error:
        errors = json.loads(json.dumps(error.errors(include_url=False), default=repr))
        return 'invalid', {'errors': errors}
    dumped = instance.model_dump_json()
    observed: Json = {
        'json': dumped,
        'json_by_alias_exclude_none': instance.model_dump_json(by_alias=True, exclude_none=True),
    }
    python = _python_shape(instance.model_dump())
    if python != json.loads(dumped):
        observed['python'] = python
    return 'valid', observed


def _digest(observed: Json) -> str:
    return hashlib.sha256(_line(observed).encode()).hexdigest()[:32]


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding='utf-8').splitlines()


def _line_name(line: str) -> str:
    """Return the model, export or definition a snapshot line belongs to."""
    parsed = cast('list[Any]', json.loads(line))
    return str(parsed[1] if len(parsed) == 3 else parsed[0])  # noqa: PLR2004 - kind, name, entry


def _check(path: Path, lines: tuple[str, ...], explain: dict[str, str] | None = None) -> None:
    if UPDATE:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(f'{line}\n' for line in lines), encoding='utf-8', newline='\n')
        return
    expected = _read_lines(path)
    if list(lines) == expected:
        return
    live, stored = set(lines), set(expected)
    removed = [line for line in expected if line not in live]
    added = [line for line in lines if line not in stored]
    names = sorted({_line_name(line) for line in removed + added}) or ['(ordering only)']
    details = '\n'.join(f'{name}: {explain[name]}' for name in names if explain and name in explain)
    pytest.fail(f'{path.name}: wire snapshot changed for {", ".join(names[:20])}\n{details}'[:4000])


@pytest.mark.parametrize('stem', ['_defs', *SUBPACKAGES])
def test_json_schemas_are_unchanged(stem: str) -> None:
    """Every model schema (both modes), shared definition and exported alias is unchanged."""
    _check(SNAPSHOTS / 'schemas' / f'{stem}.jsonl', _schema_lines()[stem])


@pytest.mark.parametrize('subpackage', SUBPACKAGES)
def test_serialization_and_validation_errors_are_unchanged(subpackage: str) -> None:
    """Recorded inputs serialize, or fail validation, exactly as recorded."""
    path = SNAPSHOTS / 'instances' / f'{subpackage}.jsonl'
    models = _models(subpackage)
    lines: list[str] = []
    explain: dict[str, str] = {}
    for recorded in _read_lines(path):
        name, entries = cast('tuple[str, list[list[Any]]]', tuple(json.loads(recorded)))
        assert name in models, f'{subpackage}: recorded model {name} no longer exists'
        observed_entries: list[list[Any]] = []
        for mode, payload, verdict, digest in entries:
            observed_verdict, observed = _observe(models[name], mode, payload)
            observed_digest = _digest(observed)
            if (observed_verdict, observed_digest) != (verdict, digest):
                explain.setdefault(name, f'{observed_verdict} {_line(observed)[:600]}')
            observed_entries.append([mode, payload, observed_verdict, observed_digest])
        lines.append(_line([name, observed_entries]))
    _check(path, tuple(lines), explain)
