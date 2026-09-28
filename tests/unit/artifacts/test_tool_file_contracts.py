# pyright: strict
"""Contracts for SDK-local generated files and ordinary artifact intake."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import maivn_contracts.artifacts as artifact_contracts

GeneratedFile: Any = getattr(artifact_contracts, 'GeneratedFile', None)
ToolFileIntakeAccepted: Any = getattr(artifact_contracts, 'ToolFileIntakeAccepted', None)
ToolFileIntakeManifest: Any = getattr(artifact_contracts, 'ToolFileIntakeManifest', None)
requires_tool_file_contracts = pytest.mark.skipif(
    GeneratedFile is None,
    reason='tool-file contracts are not implemented yet',
)

DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
SHA256 = 'a' * 64


def test_tool_file_contracts_are_public() -> None:
    """The SDK and toolsets need one canonical import surface."""
    assert GeneratedFile is not None
    assert ToolFileIntakeManifest is not None
    assert ToolFileIntakeAccepted is not None


def test_generated_batch_has_bounded_ordered_nominal_files() -> None:
    """A batch preserves output slots and refuses empty or unbounded uploads."""
    batch_type = getattr(artifact_contracts, 'GeneratedFiles', None)
    assert batch_type is not None
    first = _generated_file()
    second = _generated_file(
        filename='second.docx',
        path=str(Path.cwd() / 'second.docx'),
    )
    batch = batch_type.model_validate({'kind': 'generated_files', 'files': [first, second]})
    assert [file.filename for file in batch.files] == ['quarterly report.docx', 'second.docx']
    assert batch_type.model_json_schema()['x-maivn-output-kind'] == 'generated_files'
    for files in ([], [first] * 17):
        with pytest.raises(ValidationError):
            batch_type.model_validate({'kind': 'generated_files', 'files': files})


def _generated_file(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        'kind': 'generated_file',
        'artifact_kind': 'document',
        'filename': 'quarterly report.docx',
        'path': str(Path.cwd() / 'quarterly report.docx'),
        'mime_type': DOCX_MIME,
        'size_bytes': 128,
        'sha256': SHA256,
        'custody': 'ordinary',
        'workspace': {
            'workspace_type': 'document',
            'document_id': 'document_0001',
        },
    }
    value.update(changes)
    return value


def _intake_manifest(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        'protocol_version': 1,
        'session_id': 'session_0001',
        'call_id': 'call_0001',
        'output_index': 0,
        'artifact_kind': 'document',
        'filename': 'quarterly report.docx',
        'mime_type': DOCX_MIME,
        'size_bytes': 128,
        'sha256': SHA256,
        'custody': 'ordinary',
    }
    value.update(changes)
    return value


@requires_tool_file_contracts
def test_generated_file_is_nominal_and_keeps_optional_matching_bytes_local() -> None:
    """The discriminator enables contract-based intake without shape heuristics."""
    generated = GeneratedFile.model_validate(
        _generated_file(content_base64='YWJjZA=='),
    )

    assert generated.kind == 'generated_file'
    assert generated.custody == 'ordinary'
    assert generated.content_base64 == 'YWJjZA=='
    assert generated.workspace == {
        'workspace_type': 'document',
        'document_id': 'document_0001',
    }
    schema = GeneratedFile.model_json_schema()
    assert schema['x-maivn-output-kind'] == 'generated_file'
    assert schema['properties']['kind']['const'] == 'generated_file'
    assert {'kind', 'path', 'custody'} <= set(schema['required'])
    assert 'content_base64' not in schema['required']


@pytest.mark.parametrize(
    'changes',
    [
        {'kind': 'file'},
        {'path': 'relative/report.docx'},
        {'path': str(Path.cwd() / 'different.docx')},
        {'filename': '../report.docx'},
        {'artifact_kind': 'spreadsheet'},
        {'mime_type': 'application/pdf'},
        {'size_bytes': 0},
        {'sha256': 'A' * 64},
        {'custody': 'unknown'},
        {'unexpected': 'field'},
    ],
)
@requires_tool_file_contracts
def test_generated_file_rejects_ambiguous_or_unsafe_local_sources(
    changes: dict[str, object],
) -> None:
    """Unsafe paths, identity mismatches, and unknown custody fail closed."""
    with pytest.raises(ValidationError):
        GeneratedFile.model_validate(_generated_file(**changes))


@requires_tool_file_contracts
def test_intake_manifest_contains_only_network_safe_file_facts() -> None:
    """Local sources must be absent from the network control frame."""
    manifest = ToolFileIntakeManifest.model_validate(_intake_manifest())

    dumped = manifest.model_dump(mode='json', exclude_none=True)
    assert dumped == _intake_manifest()
    assert 'path' not in dumped
    assert 'content_base64' not in dumped
    assert set(ToolFileIntakeManifest.model_fields) == {
        'protocol_version',
        'session_id',
        'call_id',
        'output_index',
        'artifact_kind',
        'filename',
        'mime_type',
        'size_bytes',
        'sha256',
        'custody',
        'expected_base',
        'source_archive',
    }


@pytest.mark.parametrize(
    'changes',
    [
        {'protocol_version': 2},
        {'output_index': -1},
        {'artifact_kind': 'image'},
        {'filename': 'folder/report.docx'},
        {'mime_type': 'application/pdf'},
        {'path': 'C:/private/report.docx'},
        {'content_base64': 'c2VjcmV0'},
        {'custody': 'unknown'},
    ],
)
@requires_tool_file_contracts
def test_intake_manifest_rejects_mismatch_private_custody_and_local_values(
    changes: dict[str, object],
) -> None:
    """The intake manifest cannot smuggle local values or private custody."""
    with pytest.raises(ValidationError):
        ToolFileIntakeManifest.model_validate(_intake_manifest(**changes))


@requires_tool_file_contracts
def test_intake_response_is_nominal_and_requires_an_ordinary_artifact_ref() -> None:
    """Successful intake returns the existing immutable ordinary reference."""
    fields = ToolFileIntakeAccepted.model_fields

    assert set(fields) == {'status', 'artifact', 'idempotent_replay', 'source_archive'}
    assert fields['artifact'].is_required()
    schema = ToolFileIntakeAccepted.model_json_schema()
    assert schema['properties']['status']['const'] == 'accepted'


def test_generated_file_accepts_explicit_private_custody_intent() -> None:
    """Local private intent is distinct from a committed Vault artifact reference."""
    generated = GeneratedFile.model_validate(_generated_file(custody='vault_private'))
    assert generated.custody == 'vault_private'
