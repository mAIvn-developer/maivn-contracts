"""Closed, versioned canonical Flow graph models."""

from __future__ import annotations

from collections import Counter
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    PositiveInt,
    StrictStr,
    field_serializer,
    model_validator,
)

FlowId: TypeAlias = Annotated[
    StrictStr,
    Field(
        min_length=1,
        max_length=200,
        pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$',
    ),
]
ComponentKind: TypeAlias = Literal['agent', 'swarm', 'tool', 'toolset', 'skill', 'skillset']
ResourceRelationship: TypeAlias = Literal['capability', 'knowledge', 'delegate']
EdgeKind: TypeAlias = Literal['control', 'result', 'capability', 'knowledge', 'delegation']

_RESOURCE_EDGE_KIND: dict[str, str] = {
    'capability': 'capability',
    'knowledge': 'knowledge',
    'delegate': 'delegation',
}
_RESOURCE_COMPONENT_KINDS: dict[str, frozenset[str]] = {
    'capability': frozenset({'tool', 'toolset'}),
    'knowledge': frozenset({'skill', 'skillset'}),
    'delegate': frozenset({'agent', 'swarm'}),
}


class FlowRuntimeRef(BaseModel):
    """Immutable admission-time root agent identity."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    agent_id: FlowId
    version: PositiveInt


class FlowComponentRef(BaseModel):
    """Immutable reusable component reference."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    component_id: FlowId
    version: PositiveInt
    component_kind: ComponentKind


class FlowNestedFlowRef(BaseModel):
    """Immutable same-project Nested Flow reference."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    flow_id: FlowId
    version: PositiveInt


class FlowTriggerNode(BaseModel):
    """Marker for the canonical trigger configuration owned by the Flow."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    node_id: FlowId
    kind: Literal['trigger']


class FlowScopeNode(BaseModel):
    """One executable root agent, swarm, or Nested Flow."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    node_id: FlowId
    kind: Literal['scope']
    scope_kind: Literal['agent', 'swarm', 'nested_flow']
    runtime_ref: FlowRuntimeRef
    component_ref: FlowComponentRef | None = None
    nested_flow_ref: FlowNestedFlowRef | None = None

    @model_validator(mode='after')
    def _validate_selector(self) -> FlowScopeNode:
        if self.scope_kind == 'nested_flow':
            if self.nested_flow_ref is None or self.component_ref is not None:
                message = 'a Nested Flow scope requires only nested_flow_ref'
                raise ValueError(message)
            return self
        if self.nested_flow_ref is not None:
            message = 'an agent or swarm scope cannot carry nested_flow_ref'
            raise ValueError(message)
        if self.component_ref is not None and self.component_ref.component_kind != self.scope_kind:
            message = 'scope_kind must match component_ref.component_kind'
            raise ValueError(message)
        return self


class FlowResourceNode(BaseModel):
    """Immutable tool, skill, or delegated worker attached to the root."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    node_id: FlowId
    kind: Literal['resource']
    relationship: ResourceRelationship
    component_ref: FlowComponentRef

    @model_validator(mode='after')
    def _validate_component_role(self) -> FlowResourceNode:
        allowed = _RESOURCE_COMPONENT_KINDS[self.relationship]
        if self.component_ref.component_kind not in allowed:
            message = 'resource component kind is incompatible with its relationship'
            raise ValueError(message)
        return self


class FlowOutputNode(BaseModel):
    """Marker for the canonical output configuration owned by the Flow."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    node_id: FlowId
    kind: Literal['output']


FlowNode: TypeAlias = Annotated[
    FlowTriggerNode | FlowScopeNode | FlowResourceNode | FlowOutputNode,
    Field(discriminator='kind'),
]


class FlowEdge(BaseModel):
    """One typed relationship between Flow nodes."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    edge_id: FlowId
    kind: EdgeKind
    source: FlowId
    target: FlowId


class FlowPosition(BaseModel):
    """Finite presentation coordinates for one Flow node."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    x: FiniteFloat
    y: FiniteFloat


class FlowLayout(BaseModel):
    """Bounded presentation-only Flow layout."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    node_positions: dict[FlowId, FlowPosition] = Field(
        ...,
        min_length=1,
        max_length=256,
    )


class FlowGraph(BaseModel):
    """Closed version-one authoring graph for one executable Flow."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    schema_version: Literal[1]
    nodes: tuple[FlowNode, ...] = Field(..., min_length=3, max_length=256)
    edges: tuple[FlowEdge, ...] = Field(..., min_length=2, max_length=512)
    layout: FlowLayout

    @property
    def root_scope(self) -> FlowScopeNode:
        """Return the single root scope proven by graph validation."""
        return next(node for node in self.nodes if isinstance(node, FlowScopeNode))

    @field_serializer('nodes')
    def _serialize_nodes(self, nodes: tuple[FlowNode, ...]) -> list[object]:
        """Keep optional selectors absent so serialized graphs remain schema-valid."""
        return [node.model_dump(mode='json', exclude_none=True) for node in nodes]

    @model_validator(mode='after')
    def _validate_topology(self) -> FlowGraph:
        node_ids = [node.node_id for node in self.nodes]
        edge_ids = [edge.edge_id for edge in self.edges]
        _ensure_unique_ids(node_ids, edge_ids)
        trigger_id, scope_id, output_id = _required_node_ids(self.nodes)
        nodes = {node.node_id: node for node in self.nodes}
        _ensure_references_exist(nodes, self.edges, self.layout)
        _ensure_execution_edges(self.edges, trigger_id, scope_id, output_id)
        _ensure_resource_edges(nodes, self.edges, scope_id)
        _ensure_acyclic(node_ids, self.edges)
        return self


def _ensure_unique_ids(node_ids: list[str], edge_ids: list[str]) -> None:
    if len(set(node_ids)) != len(node_ids):
        message = 'Flow node ids must be unique'
        raise ValueError(message)
    if len(set(edge_ids)) != len(edge_ids):
        message = 'Flow edge ids must be unique'
        raise ValueError(message)


def _required_node_ids(nodes: tuple[FlowNode, ...]) -> tuple[str, str, str]:
    kinds = Counter(node.kind for node in nodes)
    if kinds['trigger'] != 1 or kinds['scope'] != 1 or kinds['output'] != 1:
        message = 'Flow requires exactly one trigger, scope, and output node'
        raise ValueError(message)
    trigger_id = next(node.node_id for node in nodes if node.kind == 'trigger')
    scope_id = next(node.node_id for node in nodes if node.kind == 'scope')
    output_id = next(node.node_id for node in nodes if node.kind == 'output')
    return trigger_id, scope_id, output_id


def _ensure_references_exist(
    nodes: dict[str, FlowNode],
    edges: tuple[FlowEdge, ...],
    layout: FlowLayout,
) -> None:
    if not set(layout.node_positions).issubset(nodes):
        message = 'Flow layout can reference only existing nodes'
        raise ValueError(message)
    if any(edge.source not in nodes or edge.target not in nodes for edge in edges):
        message = 'Flow edges can reference only existing nodes'
        raise ValueError(message)


def _ensure_execution_edges(
    edges: tuple[FlowEdge, ...],
    trigger_id: str,
    scope_id: str,
    output_id: str,
) -> None:
    control = [edge for edge in edges if edge.kind == 'control']
    result = [edge for edge in edges if edge.kind == 'result']
    if len(control) != 1 or (control[0].source, control[0].target) != (
        trigger_id,
        scope_id,
    ):
        message = 'Flow requires exactly one trigger-to-scope control edge'
        raise ValueError(message)
    if len(result) != 1 or (result[0].source, result[0].target) != (
        scope_id,
        output_id,
    ):
        message = 'Flow requires exactly one scope-to-output result edge'
        raise ValueError(message)


def _ensure_resource_edges(
    nodes: dict[str, FlowNode],
    edges: tuple[FlowEdge, ...],
    scope_id: str,
) -> None:
    resource_ids = {node.node_id for node in nodes.values() if isinstance(node, FlowResourceNode)}
    incoming_resources: set[str] = set()
    for edge in edges:
        if edge.kind in {'control', 'result'}:
            continue
        target = nodes[edge.target]
        if (
            edge.source != scope_id
            or not isinstance(target, FlowResourceNode)
            or edge.kind != _RESOURCE_EDGE_KIND[target.relationship]
        ):
            message = 'Flow resource edges must match a root resource relationship'
            raise ValueError(message)
        if edge.target in incoming_resources:
            message = 'Flow resources require exactly one incoming relationship'
            raise ValueError(message)
        incoming_resources.add(edge.target)
    if incoming_resources != resource_ids:
        message = 'Every Flow resource requires one root relationship edge'
        raise ValueError(message)


def _ensure_acyclic(node_ids: list[str], edges: tuple[FlowEdge, ...]) -> None:
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for edge in edges:
        outgoing[edge.source].append(edge.target)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            message = 'Flow graph cannot contain cycles'
            raise ValueError(message)
        if node_id in visited:
            return
        visiting.add(node_id)
        for target in outgoing[node_id]:
            visit(target)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in node_ids:
        visit(node_id)
