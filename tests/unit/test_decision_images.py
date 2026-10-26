"""Decision images retain exact, bounded bytes and refuse ambiguous carriers."""

# ruff: noqa: D103 - behavioral tests.
from __future__ import annotations

import base64
import hashlib

import pytest
from pydantic import ValidationError

from maivn_contracts.decisions import DecisionImage

PNG = b'\x89PNG\r\n\x1a\n' + b'public image fixture'


def test_image_bytes_roundtrip_and_immutable() -> None:
    image = DecisionImage.from_bytes(PNG, 'image/png')
    assert base64.b64decode(image.inline_base64) == PNG
    assert image.size_bytes == len(PNG)
    assert image.content_hash == hashlib.sha256(PNG).hexdigest()
    assert image.inline_base64 not in repr(image)
    assert DecisionImage.model_validate_json(image.model_dump_json()) == image
    with pytest.raises(ValidationError):
        image.size_bytes = 3


@pytest.mark.parametrize(
    ('mime', 'raw'),
    [
        ('image/png', PNG),
        ('image/jpeg', b'\xff\xd8\xfffixture'),
        ('image/webp', b'RIFF1234WEBPfixture'),
    ],
)
def test_supported_container_signatures(mime: str, raw: bytes) -> None:
    image = DecisionImage.model_validate(
        {
            'mime_type': mime,
            'inline_base64': base64.b64encode(raw).decode(),
            'size_bytes': len(raw),
            'content_hash': hashlib.sha256(raw).hexdigest(),
        }
    )
    assert image.size_bytes == len(raw)


@pytest.mark.parametrize(
    'change',
    [
        {'inline_base64': 'not base64'},
        {'inline_base64': 'AB=='},
        {'size_bytes': 1},
        {'size_bytes': True},
        {'content_hash': '0' * 64},
        {'mime_type': 'image/jpeg'},
        {'mime_type': 'image/gif'},
        {'url': 'https://example.test/image.png'},
        {'storage_ref': 'private'},
    ],
)
def test_malformed_or_inconsistent_image_is_refused(change: dict[str, object]) -> None:
    payload = DecisionImage.from_bytes(PNG, 'image/png').model_dump()
    with pytest.raises(ValidationError) as error:
        DecisionImage.model_validate({**payload, **change})
    assert 'input_value=' not in str(error.value)


def test_forged_instance_is_revalidated() -> None:
    image = DecisionImage.from_bytes(PNG, 'image/png').model_copy(update={'size_bytes': 1})
    with pytest.raises(ValidationError):
        DecisionImage.model_validate(image)


def test_oversized_image_is_refused() -> None:
    with pytest.raises(ValidationError):
        DecisionImage.from_bytes(PNG + b'x' * (1024 * 1024), 'image/png')
