"""Contracts for SDK-local generated files and ordinary artifact intake."""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Literal

from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from maivn_contracts.artifacts.primitives import (
    ArtifactKind,
    ArtifactRefInvariantError,
    ClosedModel,
    MimeType,
    OpaqueTokenId,
    PositiveStrictInt,
    Sha256Hex,
    is_mime_type_valid_for_artifact_kind,
)
from maivn_contracts.artifacts.refs import (
    OrdinaryArtifactRef,  # noqa: TC001 - Pydantic resolves this annotation at runtime.
    PrivateArtifactRef,  # noqa: TC001 - Pydantic resolves this annotation at runtime.
)
from maivn_contracts.artifacts.vault_types import (
    AsciiSafeExportFilename,  # noqa: TC001 - Pydantic resolves this annotation at runtime.
)

__all__ = [
    'GeneratedFile',
    'GeneratedFiles',
    'ToolFileIntakeAccepted',
    'ToolFileIntakeManifest',
    'ToolFileSourceDescriptor',
    'ToolFileSourceRequest',
]

OutputIndex = Annotated[StrictInt, Field(ge=0, le=99)]
_FILENAME_SUFFIXES_BY_MIME: dict[str, tuple[str, ...]] = {
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ('.docx',),
    'application/pdf': ('.pdf',),
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ('.xlsx',),
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': ('.pptx',),
    'image/png': ('.png',),
    'image/jpeg': ('.jpeg', '.jpg'),
    'audio/mpeg': ('.mp3',),
    'audio/wav': ('.wav',),
    'application/octet-stream': (),
}


def _validate_file_identity(
    artifact_kind: ArtifactKind,
    mime_type: MimeType,
    filename: str,
) -> None:
    if not is_mime_type_valid_for_artifact_kind(artifact_kind, mime_type):
        raise ArtifactRefInvariantError
    suffixes = _FILENAME_SUFFIXES_BY_MIME[mime_type]
    if suffixes and not filename.lower().endswith(suffixes):
        raise ArtifactRefInvariantError


class GeneratedFile(ClosedModel):
    """A file produced in the SDK host and not yet admitted to platform custody."""

    model_config = ConfigDict(json_schema_extra={'x-maivn-output-kind': 'generated_file'})

    kind: Literal['generated_file']
    artifact_kind: ArtifactKind
    filename: AsciiSafeExportFilename
    path: StrictStr = Field(min_length=1, max_length=4096)
    mime_type: MimeType
    size_bytes: PositiveStrictInt
    sha256: Sha256Hex
    custody: Literal['ordinary', 'vault_private']
    expected_base: OrdinaryArtifactRef | None = None
    private_expected_base: PrivateArtifactRef | None = None
    workspace: dict[StrictStr, StrictStr] | None = None
    content_base64: StrictStr | None = None

    @field_validator('path')
    @classmethod
    def _validate_absolute_path(cls, value: str) -> str:
        if '\x00' in value:
            raise ArtifactRefInvariantError
        windows_path = PureWindowsPath(value)
        posix_path = PurePosixPath(value)
        if not windows_path.is_absolute() and not posix_path.is_absolute():
            raise ArtifactRefInvariantError
        return value

    @model_validator(mode='after')
    def _validate_identity(self) -> GeneratedFile:
        _validate_file_identity(self.artifact_kind, self.mime_type, self.filename)
        if self.expected_base is not None and (
            self.private_expected_base is not None or self.custody == 'vault_private'
        ):
            raise ArtifactRefInvariantError
        for base in (self.expected_base, self.private_expected_base):
            if base is not None and (
                base.kind != self.artifact_kind or base.mime_type != self.mime_type
            ):
                raise ArtifactRefInvariantError
        windows_path = PureWindowsPath(self.path)
        path_name = (
            windows_path.name if windows_path.is_absolute() else PurePosixPath(self.path).name
        )
        if path_name != self.filename:
            raise ArtifactRefInvariantError
        return self


class GeneratedFiles(ClosedModel):
    """An ordered bounded batch of SDK-local files with stable output slots."""

    model_config = ConfigDict(json_schema_extra={'x-maivn-output-kind': 'generated_files'})

    kind: Literal['generated_files']
    files: tuple[GeneratedFile, ...] = Field(min_length=1, max_length=16)


class ToolFileSourceDescriptor(ClosedModel):
    """Content commitment for the hidden portable editable source part."""

    format: Literal['maivn-source-archive-v1'] = 'maivn-source-archive-v1'
    size_bytes: PositiveStrictInt = Field(le=52_428_800)
    sha256: Sha256Hex


class ToolFileSourceRequest(ClosedModel):
    """Select source custody by exact artifact and authenticated conversation."""

    artifact_ref: OrdinaryArtifactRef
    session_id: OpaqueTokenId


class ToolFileIntakeManifest(ClosedModel):
    """Network-safe control frame preceding one generated-file byte stream."""

    protocol_version: Literal[1] = 1
    session_id: OpaqueTokenId
    call_id: OpaqueTokenId
    output_index: OutputIndex
    artifact_kind: ArtifactKind
    filename: AsciiSafeExportFilename
    mime_type: MimeType
    size_bytes: PositiveStrictInt
    sha256: Sha256Hex
    custody: Literal['ordinary'] = 'ordinary'
    expected_base: OrdinaryArtifactRef | None = None
    source_archive: ToolFileSourceDescriptor | None = None

    @model_validator(mode='after')
    def _validate_identity(self) -> ToolFileIntakeManifest:
        _validate_file_identity(self.artifact_kind, self.mime_type, self.filename)
        return self


class ToolFileIntakeAccepted(ClosedModel):
    """Successful admission of one SDK-local file into ordinary custody."""

    status: Literal['accepted'] = 'accepted'
    artifact: OrdinaryArtifactRef
    idempotent_replay: StrictBool = False
    source_archive: ToolFileSourceDescriptor | None = None
