"""Deployed-agent registry contract loaders, validators, and typed models.

This module owns the public Python interface for `libraries/maivn-contracts/agents`.
It depends only on the checked-in JSON contract files, Pydantic, and
jsonschema. It does not import any other mAIvn runtime module.
"""

from __future__ import annotations

from maivn_contracts.agents.fingerprint import (
    FINGERPRINT_ALGORITHM,
    definition_digest,
    digests_differ,
)
from maivn_contracts.agents.loaders import (
    load_agent_schema,
    load_agent_version_schema,
    load_message_binding_schema,
    validate_agent,
    validate_agent_version,
    validate_message_binding,
)
from maivn_contracts.agents.model import (
    Agent,
    AgentMemoryExtractionPolicy,
    AgentMemoryPolicy,
    AgentMemoryRetrievalPolicy,
    AgentOutputSchema,
    AgentPeerDependency,
    AgentToolDependency,
    AgentVersion,
    CallableMessageBinding,
    HostedToolExecution,
    InlineInstructions,
    InvokeAgentSpec,
    InvokeSystemToolsConfig,
    MessageBinding,
    ModelChoice,
    ModelSettings,
    PlanningChoice,
    PlanningTier,
    ReferenceInstructions,
    TemplateMessageBinding,
    ToolExecution,
    ToolSnapshot,
    VersionOptions,
    WebhookEndpoint,
    WebhookToolExecution,
    WorkerToolExecution,
)
from maivn_contracts.agents.serving import (
    DefinitionDigest,
    ServedAgent,
    ServedVersion,
    ServingManifest,
    ServingState,
    ServingTransport,
)

__all__ = [
    'FINGERPRINT_ALGORITHM',
    'Agent',
    'AgentMemoryExtractionPolicy',
    'AgentMemoryPolicy',
    'AgentMemoryRetrievalPolicy',
    'AgentOutputSchema',
    'AgentPeerDependency',
    'AgentToolDependency',
    'AgentVersion',
    'CallableMessageBinding',
    'DefinitionDigest',
    'HostedToolExecution',
    'InlineInstructions',
    'InvokeAgentSpec',
    'InvokeSystemToolsConfig',
    'MessageBinding',
    'ModelChoice',
    'ModelSettings',
    'PlanningChoice',
    'PlanningTier',
    'ReferenceInstructions',
    'ServedAgent',
    'ServedVersion',
    'ServingManifest',
    'ServingState',
    'ServingTransport',
    'TemplateMessageBinding',
    'ToolExecution',
    'ToolSnapshot',
    'VersionOptions',
    'WebhookEndpoint',
    'WebhookToolExecution',
    'WorkerToolExecution',
    'definition_digest',
    'digests_differ',
    'load_agent_schema',
    'load_agent_version_schema',
    'load_message_binding_schema',
    'validate_agent',
    'validate_agent_version',
    'validate_message_binding',
]
