# pyright: strict
"""Contract tests for the messages module public interface."""

from __future__ import annotations

from maivn_contracts import messages
from maivn_contracts.messages import (
    Attachment,
    DocumentContentBlock,
    ImageContentBlock,
    Message,
    PIIWhitelistEntry,
    RedactionConfig,
    TextContentBlock,
    VideoContentBlock,
    load_attachment_schema,
    load_message_schema,
)


def test_public_interface_exports_are_pinned() -> None:
    """Expose the pinned public messages module exports."""
    assert set(messages.__all__) == {
        'Attachment',
        'AttachmentStorageRef',
        'ContentBlock',
        'CoverRegion',
        'DocumentContentBlock',
        'ImageContentBlock',
        'KnownPrivateData',
        'Message',
        'MessageRole',
        'MetadataValue',
        'PIIWhitelist',
        'PIIWhitelistEntry',
        'RedactionConfig',
        'RedactionPreviewRequest',
        'RedactionPreviewResponse',
        'TextContentBlock',
        'VideoContentBlock',
        'load_attachment_schema',
        'load_message_schema',
        'validate_attachment',
        'validate_message',
    }

    for exported_name in messages.__all__:
        assert hasattr(messages, exported_name)


def test_attachment_model_and_json_schema_agree_field_for_field() -> None:
    """Keep the Attachment model and JSON Schema field sets aligned."""
    schema = load_attachment_schema()

    schema_fields = set(schema['properties'])
    model_fields = set(Attachment.model_fields)
    required_model_fields = {
        name for name, field in Attachment.model_fields.items() if field.is_required()
    }

    assert model_fields == schema_fields
    assert required_model_fields == set(schema['required'])


def test_message_model_and_json_schema_agree_field_for_field() -> None:
    """Keep the Message model and JSON Schema field sets aligned."""
    schema = load_message_schema()

    schema_fields = set(schema['properties'])
    model_fields = set(Message.model_fields)
    required_model_fields = {
        name for name, field in Message.model_fields.items() if field.is_required()
    }

    assert model_fields == schema_fields
    assert required_model_fields == set(schema['required'])


def test_content_block_variants_and_json_schema_agree_field_for_field() -> None:
    """Keep content block variant models aligned with schema definitions."""
    schema = load_message_schema()

    assert set(TextContentBlock.model_fields) == set(
        schema['$defs']['textContentBlock']['properties'],
    )
    assert set(ImageContentBlock.model_fields) == set(
        schema['$defs']['imageContentBlock']['properties'],
    )
    assert set(DocumentContentBlock.model_fields) == set(
        schema['$defs']['documentContentBlock']['properties'],
    )
    assert set(VideoContentBlock.model_fields) == set(
        schema['$defs']['videoContentBlock']['properties'],
    )


def test_redaction_models_and_json_schema_agree_field_for_field() -> None:
    """Keep redaction config and whitelist entries aligned with schema definitions."""
    schema = load_message_schema()

    assert set(RedactionConfig.model_fields) == set(
        schema['$defs']['redactionConfig']['properties'],
    )
    assert set(PIIWhitelistEntry.model_fields) == set(
        schema['$defs']['piiWhitelistEntry']['properties'],
    )
