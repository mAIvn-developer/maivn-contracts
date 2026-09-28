"""Cross-language request projections retain private action field constraints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

from jsonschema import Draft202012Validator

from maivn_contracts.artifacts.attachment_schemas import private_artifact_resolve_request_schema

if TYPE_CHECKING:
    from collections.abc import Callable


def test_private_action_schema_matches_generated_source() -> None:
    """Consumers must receive the current source-owned request schema."""
    path = (
        Path(__file__).resolve().parents[3]
        / 'artifacts'
        / 'private_artifact_resolve_request.schema.json'
    )
    schema = private_artifact_resolve_request_schema()
    Draft202012Validator.check_schema(schema)
    assert json.loads(path.read_text(encoding='utf-8')) == schema


def test_action_branches_reject_missing_or_cross_action_inputs() -> None:
    """JSON-only callers cannot mix deletion, export and download authority."""
    schema = private_artifact_resolve_request_schema()
    # The root schema validates the ref; isolate action branches to exhaust their
    # presence/null constraints without duplicating a private reference fixture.
    validator = Draft202012Validator({'oneOf': schema['oneOf'], '$defs': schema['$defs']})
    is_valid = cast('Callable[[object], bool]', validator.is_valid)
    valid = [
        {'client_proof_digest': 'a' * 64},
        {'client_proof_digest': 'a' * 64, 'retrieval_part': 'editable_source'},
        {'operation': 'redacted_export', 'export_filename': 'report.pdf'},
        {'operation': 'delete', 'deletion_scope': {'mode': 'private_only'}},
    ]
    for request in valid:
        assert is_valid(request)
    invalid = [
        {},
        {'client_proof_digest': None},
        {'operation': 'delete'},
        {'operation': 'redacted_export', 'export_filename': None},
        {'operation': 'delete', 'deletion_scope': 'all', 'client_proof_digest': 'a' * 64},
        {'export_filename': 'report.pdf'},
        {
            'operation': 'redacted_export',
            'export_filename': 'report.pdf',
            'retrieval_part': 'editable_source',
        },
        {
            'operation': 'delete',
            'deletion_scope': {'mode': 'private_only'},
            'retrieval_part': 'editable_source',
        },
    ]
    for request in invalid:
        assert not is_valid(request)
