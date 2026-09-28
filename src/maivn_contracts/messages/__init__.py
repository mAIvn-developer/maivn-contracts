"""Owned Message contract loaders, validators, and typed models.

This module owns the public Python interface for `libraries/maivn-contracts/messages`.
It depends only on the checked-in JSON contract files, Pydantic, and
jsonschema. It does not import any other mAIvn runtime module.
"""

from __future__ import annotations

from maivn_contracts.messages.loaders import (
    load_attachment_schema,
    load_message_schema,
    validate_attachment,
    validate_message,
)
from maivn_contracts.messages.model import (
    Attachment,
    AttachmentStorageRef,
    ContentBlock,
    DocumentContentBlock,
    ImageContentBlock,
    KnownPrivateData,
    Message,
    MessageRole,
    MetadataValue,
    PIIWhitelist,
    PIIWhitelistEntry,
    RedactionConfig,
    TextContentBlock,
    VideoContentBlock,
)

__all__ = [
    'Attachment',
    'AttachmentStorageRef',
    'ContentBlock',
    'DocumentContentBlock',
    'ImageContentBlock',
    'KnownPrivateData',
    'Message',
    'MessageRole',
    'MetadataValue',
    'PIIWhitelist',
    'PIIWhitelistEntry',
    'RedactionConfig',
    'TextContentBlock',
    'VideoContentBlock',
    'load_attachment_schema',
    'load_message_schema',
    'validate_attachment',
    'validate_message',
]
