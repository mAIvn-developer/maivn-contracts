"""The preview contract never returns value maps or accepts run configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from maivn_contracts.messages import RedactionPreviewRequest, RedactionPreviewResponse
from maivn_contracts.messages.redaction_preview import PreviewItem, PreviewRegion


def test_preview_request_rejects_thread_and_pattern_controls() -> None:
    """The endpoint cannot be used to create or resume a conversation."""
    for field in ('thread_id', 'redact_patterns', 'run_config'):
        with pytest.raises(ValidationError):
            RedactionPreviewRequest.model_validate({'prompt': 'hello', field: 'forbidden'})


def test_preview_response_rejects_private_value_maps() -> None:
    """A response with a private-data map is a wire contract violation."""
    with pytest.raises(ValidationError):
        RedactionPreviewResponse.model_validate({'inputs': [], 'private_data': {'name': 'secret'}})
    with pytest.raises(ValidationError):
        PreviewItem.model_validate(
            {
                'key': 'name',
                'placeholder': '{_{name}_}',
                'pii_type': 'person',
                'source': 'declared',
                'input_index': 0,
                'value': 'secret',
            }
        )


def test_picture_regions_require_one_based_pages_and_page_fractions() -> None:
    """Pixel coordinates cannot accidentally enter the public region contract."""
    assert PreviewRegion(page=1, bbox=(0.1, 0.2, 0.3, 0.4)).page == 1
    with pytest.raises(ValidationError):
        PreviewRegion(page=0, bbox=(0.1, 0.2, 0.3, 0.4))
    with pytest.raises(ValidationError):
        PreviewRegion(page=1, bbox=(10, 20, 30, 40))


def test_approved_request_is_hidden_from_repr_and_round_trips() -> None:
    """The sealed message copy survives JSON without flattening its structured text."""
    response = RedactionPreviewResponse.model_validate(
        {
            'preview_id': 'ticket',
            'inputs': [],
            'approved_request': [
                {
                    'message_id': 'preview',
                    'role': 'user',
                    'content': [{'type': 'text', 'text': 'Hello {_{candidate}_}.  \n'}],
                    'redaction': {},
                    'ts': '2026-10-26T12:00:00Z',
                }
            ],
        }
    )
    assert RedactionPreviewResponse.model_validate_json(response.model_dump_json()) == response
    assert 'candidate' not in repr(response)
    with pytest.raises(ValidationError):
        RedactionPreviewResponse.model_validate({'inputs': [], 'approved_request': []})
