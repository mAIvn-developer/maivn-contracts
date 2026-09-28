# pyright: strict
"""Unit tests for ToolSet contract models."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from maivn_contracts.toolsets import ToolSet, ToolSetRef


def test_tool_set_accepts_tool_and_nested_tool_set_members() -> None:
    """ToolSet members are discriminated Tool and nested ToolSet refs."""
    tool_set = ToolSet.model_validate(
        {
            'toolset_id': 'tset-customer-support',
            'org_id': 'org-acme',
            'name': 'Customer support tools',
            'description': 'Reusable support connector set.',
            'members': [
                {
                    'kind': 'tool',
                    'tool_id': 'tool-slack-send-message',
                    'namespace': 'connectors.slack',
                    'version': '2026-07-06',
                },
                {
                    'kind': 'toolset',
                    'toolset_id': 'tset-shared-http',
                    'namespace': 'connectors.http',
                    'version': '2026-07-06',
                },
            ],
            'created_at': '2026-07-06T15:00:00Z',
            'updated_at': '2026-07-06T15:00:00Z',
        },
    )

    assert tool_set.members[0].kind == 'tool'
    assert tool_set.members[1] == ToolSetRef(
        kind='toolset',
        toolset_id='tset-shared-http',
        namespace='connectors.http',
        version='2026-07-06',
    )


def test_tool_set_allows_empty_members() -> None:
    """Empty ToolSets are valid drafts before any child refs are wired."""
    tool_set = ToolSet(
        toolset_id='tset-empty',
        org_id='org-acme',
        name='Empty draft',
        members=[],
        created_at='2026-07-06T15:00:00Z',
        updated_at='2026-07-06T15:00:00Z',
    )

    assert tool_set.members == []


def test_tool_set_rejects_extra_fields_and_missing_member_discriminator() -> None:
    """Strict ToolSet contracts reject unknown fields and ambiguous members."""
    base: dict[str, Any] = {
        'toolset_id': 'tset-extra',
        'org_id': 'org-acme',
        'name': 'Extra',
        'members': [],
        'created_at': '2026-07-06T15:00:00Z',
        'updated_at': '2026-07-06T15:00:00Z',
    }

    with pytest.raises(ValidationError):
        ToolSet.model_validate(base | {'unexpected': True})

    with pytest.raises(ValidationError):
        ToolSet.model_validate(
            base
            | {
                'members': [
                    {
                        'tool_id': 'tool-slack-send-message',
                        'namespace': 'connectors.slack',
                        'version': '2026-07-06',
                    },
                ],
            },
        )
