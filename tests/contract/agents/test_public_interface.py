# pyright: strict
"""Contract tests for the agents module public interface."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pydantic import BaseModel

import jsonschema

from maivn_contracts import agents
from maivn_contracts.agents import (
    Agent,
    AgentToolDependency,
    AgentVersion,
    CallableMessageBinding,
    TemplateMessageBinding,
    load_agent_schema,
    load_agent_version_schema,
    load_message_binding_schema,
)


def test_public_interface_exports_are_pinned() -> None:
    """Expose the pinned public agents module exports."""
    assert set(agents.__all__) == {
        'Agent',
        'digests_differ',
        'definition_digest',
        'ServingTransport',
        'ServingState',
        'ServingManifest',
        'ServedVersion',
        'ServedAgent',
        'FINGERPRINT_ALGORITHM',
        'DefinitionDigest',
        'AgentPeerDependency',
        'AgentMemoryExtractionPolicy',
        'AgentMemoryPolicy',
        'AgentMemoryRetrievalPolicy',
        'AgentOutputSchema',
        'AgentToolDependency',
        'AgentVersion',
        'CallableMessageBinding',
        'InlineInstructions',
        'InvokeAgentSpec',
        'InvokeSystemToolsConfig',
        'MessageBinding',
        'ModelChoice',
        'ModelSettings',
        'PlanningChoice',
        'PlanningTier',
        'ReferenceInstructions',
        'TemplateMessageBinding',
        'HostedToolExecution',
        'ToolExecution',
        'WebhookToolExecution',
        'WorkerToolExecution',
        'ToolSnapshot',
        'VersionOptions',
        'WebhookEndpoint',
        'load_agent_schema',
        'load_agent_version_schema',
        'load_message_binding_schema',
        'validate_agent',
        'validate_agent_version',
        'validate_message_binding',
    }

    for exported_name in agents.__all__:
        assert hasattr(agents, exported_name)


def test_agent_model_and_json_schema_agree_field_for_field() -> None:
    """Keep the Agent model and JSON Schema field sets aligned."""
    schema = load_agent_schema()

    schema_fields = set(schema['properties'])
    model_fields = set(Agent.model_fields)
    required_model_fields = {
        name for name, field in Agent.model_fields.items() if field.is_required()
    }

    assert model_fields == schema_fields
    assert required_model_fields == set(schema['required'])


def test_agent_version_model_and_json_schema_agree_field_for_field() -> None:
    """Keep the AgentVersion model and JSON Schema field sets aligned."""
    schema = load_agent_version_schema()

    schema_fields = set(schema['properties'])
    model_fields = set(AgentVersion.model_fields)
    required_model_fields = {
        name for name, field in AgentVersion.model_fields.items() if field.is_required()
    }

    assert model_fields == schema_fields
    assert required_model_fields == set(schema['required'])

    memory_schema = schema['$defs']['agentMemoryPolicy']
    assert set(memory_schema['required']) == {
        'enabled',
        'level',
        'persistence_mode',
        'retrieval',
        'skill_extraction',
        'insight_extraction',
    }
    assert memory_schema['additionalProperties'] is False
    assert schema['$defs']['agentOutputSchema']['additionalProperties'] is False


def test_message_binding_variants_and_json_schema_agree_field_for_field() -> None:
    """Keep message binding variant models aligned with their schema definitions."""
    schema = load_message_binding_schema()
    template_schema = schema['$defs']['templateMessageBinding']
    callable_schema = schema['$defs']['callableMessageBinding']

    assert set(TemplateMessageBinding.model_fields) == set(template_schema['properties'])
    assert {
        name for name, field in TemplateMessageBinding.model_fields.items() if field.is_required()
    } == set(template_schema['required'])
    assert set(CallableMessageBinding.model_fields) == set(callable_schema['properties'])
    assert {
        name for name, field in CallableMessageBinding.model_fields.items() if field.is_required()
    } == set(callable_schema['required'])


def test_every_agent_version_model_dump_validates_against_its_own_schema() -> None:
    """Parse -> dump -> validate must round trip, for every nested model.

    `AgentToolDependency` gained an `optional` field in Python that the schema
    forbade as an additional property, so publishing any agent version carrying
    a tool-dependency edge failed - the control plane revalidates a serialized
    model before insertion, and registry reads revalidate too.

    Asserting one field would only catch the one already found. This walks the
    schema's own `$defs`, so the next model that grows a field the schema does
    not know about fails here rather than at publication.
    """
    definitions = cast('dict[str, Any]', load_agent_version_schema()['$defs'])

    specimens: dict[str, BaseModel] = {
        'agentToolDependency': AgentToolDependency(
            tool_id='summarize', agent_name='researcher', arg_name='notes'
        ),
    }

    for schema_name, specimen in specimens.items():
        dumped = specimen.model_dump(mode='json')
        jsonschema.validate(dumped, definitions[schema_name])
        assert type(specimen).model_validate(dumped) == specimen, schema_name
