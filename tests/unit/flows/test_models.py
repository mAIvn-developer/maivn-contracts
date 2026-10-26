# pyright: strict
"""Unit tests for the closed canonical Flow graph contract."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any, TypeAlias, cast

import pytest
from pydantic import ValidationError

from maivn_contracts.flows import FlowGraph

COMPONENT_VERSION = 7
RESOURCE_NODE_COUNT = 6
RESOURCE_EDGE_COUNT = 5
GraphBody: TypeAlias = dict[str, Any]
GraphMutation: TypeAlias = Callable[[GraphBody], None]


def _minimal_graph() -> dict[str, Any]:
    return {
        'schema_version': 1,
        'nodes': [
            {'node_id': 'trigger', 'kind': 'trigger'},
            {
                'node_id': 'scope',
                'kind': 'scope',
                'scope_kind': 'agent',
                'runtime_ref': {'agent_id': 'agent-support', 'version': 3},
                'component_ref': {
                    'component_id': 'cmp-support',
                    'version': COMPONENT_VERSION,
                    'component_kind': 'agent',
                },
            },
            {'node_id': 'output', 'kind': 'output'},
        ],
        'edges': [
            {
                'edge_id': 'start',
                'kind': 'control',
                'source': 'trigger',
                'target': 'scope',
            },
            {
                'edge_id': 'finish',
                'kind': 'result',
                'source': 'scope',
                'target': 'output',
            },
        ],
        'layout': {
            'node_positions': {
                'trigger': {'x': 80, 'y': 120},
                'scope': {'x': 320, 'y': 120},
                'output': {'x': 560, 'y': 120},
            },
        },
    }


def test_minimal_flow_graph_is_closed_and_versioned() -> None:
    """Accept one trigger, executable scope, and output with immutable identity."""
    graph = FlowGraph.model_validate(_minimal_graph())

    assert graph.schema_version == 1
    assert graph.root_scope.runtime_ref.agent_id == 'agent-support'
    assert graph.root_scope.component_ref is not None
    assert graph.root_scope.component_ref.version == COMPONENT_VERSION
    assert graph.model_dump(mode='json', exclude_none=True) == _minimal_graph()


def test_nested_flow_scope_preserves_pin_and_resolved_runtime() -> None:
    """Represent a Nested Flow separately from its admission-time leaf agent."""
    body = _minimal_graph()
    body['nodes'][1] = {
        'node_id': 'scope',
        'kind': 'scope',
        'scope_kind': 'nested_flow',
        'runtime_ref': {'agent_id': 'agent-leaf', 'version': 4},
        'nested_flow_ref': {'flow_id': 'flow-child', 'version': 2},
    }

    graph = FlowGraph.model_validate(body)

    assert graph.root_scope.nested_flow_ref is not None
    assert graph.root_scope.nested_flow_ref.flow_id == 'flow-child'
    assert graph.root_scope.runtime_ref.agent_id == 'agent-leaf'


def test_resource_edges_are_role_compatible_and_bounded() -> None:
    """Allow real tool, skill, and delegate relationships to the root scope."""
    body = _minimal_graph()
    body['nodes'].extend(
        [
            {
                'node_id': 'tool.crm',
                'kind': 'resource',
                'relationship': 'capability',
                'component_ref': {
                    'component_id': 'cmp-crm',
                    'version': 2,
                    'component_kind': 'tool',
                },
            },
            {
                'node_id': 'skill.reply',
                'kind': 'resource',
                'relationship': 'knowledge',
                'component_ref': {
                    'component_id': 'cmp-reply',
                    'version': 5,
                    'component_kind': 'skill',
                },
            },
            {
                'node_id': 'agent.escalation',
                'kind': 'resource',
                'relationship': 'delegate',
                'component_ref': {
                    'component_id': 'cmp-escalation',
                    'version': 1,
                    'component_kind': 'agent',
                },
            },
        ],
    )
    body['edges'].extend(
        [
            {
                'edge_id': 'use.crm',
                'kind': 'capability',
                'source': 'scope',
                'target': 'tool.crm',
            },
            {
                'edge_id': 'use.reply',
                'kind': 'knowledge',
                'source': 'scope',
                'target': 'skill.reply',
            },
            {
                'edge_id': 'delegate.escalation',
                'kind': 'delegation',
                'source': 'scope',
                'target': 'agent.escalation',
            },
        ],
    )
    positions = body['layout']['node_positions']
    positions.update(
        {
            'tool.crm': {'x': 300, 'y': 300},
            'skill.reply': {'x': 450, 'y': 300},
            'agent.escalation': {'x': 600, 'y': 300},
        },
    )

    graph = FlowGraph.model_validate(body)

    assert len(graph.nodes) == RESOURCE_NODE_COUNT
    assert len(graph.edges) == RESOURCE_EDGE_COUNT


def _add_unknown_field(body: GraphBody) -> None:
    body['extra'] = True


def _add_duplicate_node(body: GraphBody) -> None:
    cast('list[GraphBody]', body['nodes']).append({'node_id': 'scope', 'kind': 'output'})


def _add_duplicate_edge(body: GraphBody) -> None:
    cast('list[GraphBody]', body['edges']).append(
        {'edge_id': 'start', 'kind': 'result', 'source': 'scope', 'target': 'output'},
    )


def _replace_with_unknown_endpoint(body: GraphBody) -> None:
    cast('list[GraphBody]', body['edges'])[1] = {
        'edge_id': 'finish',
        'kind': 'result',
        'source': 'ghost',
        'target': 'output',
    }


def _add_ghost_position(body: GraphBody) -> None:
    layout = cast('GraphBody', body['layout'])
    positions = cast('GraphBody', layout['node_positions'])
    positions['ghost'] = {'x': 0, 'y': 0}


def _add_non_finite_coordinate(body: GraphBody) -> None:
    layout = cast('GraphBody', body['layout'])
    positions = cast('GraphBody', layout['node_positions'])
    cast('GraphBody', positions['scope'])['x'] = float('nan')


def _add_invalid_node_id(body: GraphBody) -> None:
    cast('list[GraphBody]', body['nodes'])[0]['node_id'] = 'bad id'


def _add_second_scope(body: GraphBody) -> None:
    nodes = cast('list[GraphBody]', body['nodes'])
    nodes.append(deepcopy(nodes[1]) | {'node_id': 'scope-2'})


INVALID_TOPOLOGY_CASES: list[tuple[str, GraphMutation]] = [
    ('unknown top-level field', _add_unknown_field),
    ('duplicate node id', _add_duplicate_node),
    ('duplicate edge id', _add_duplicate_edge),
    ('unknown edge endpoint', _replace_with_unknown_endpoint),
    ('ghost layout position', _add_ghost_position),
    ('non-finite coordinate', _add_non_finite_coordinate),
    ('invalid node id', _add_invalid_node_id),
    ('second scope', _add_second_scope),
]


@pytest.mark.parametrize(
    'mutate',
    [mutation for _, mutation in INVALID_TOPOLOGY_CASES],
    ids=[name for name, _ in INVALID_TOPOLOGY_CASES],
)
def test_flow_graph_rejects_invalid_closed_topology(
    mutate: GraphMutation,
) -> None:
    """Reject malformed graph structure rather than guessing execution."""
    body = _minimal_graph()
    mutate(body)

    with pytest.raises(ValidationError):
        FlowGraph.model_validate(body)


@pytest.mark.parametrize(
    ('relationship', 'component_kind', 'edge_kind'),
    [
        ('capability', 'skill', 'capability'),
        ('knowledge', 'tool', 'knowledge'),
        ('delegate', 'toolset', 'delegation'),
        ('capability', 'tool', 'knowledge'),
    ],
)
def test_flow_graph_rejects_incompatible_resource_relationships(
    relationship: str,
    component_kind: str,
    edge_kind: str,
) -> None:
    """Require the node declaration and graph edge to describe the same real role."""
    body = _minimal_graph()
    body['nodes'].append(
        {
            'node_id': 'resource',
            'kind': 'resource',
            'relationship': relationship,
            'component_ref': {
                'component_id': 'cmp-resource',
                'version': 1,
                'component_kind': component_kind,
            },
        },
    )
    body['edges'].append(
        {
            'edge_id': 'resource-edge',
            'kind': edge_kind,
            'source': 'scope',
            'target': 'resource',
        },
    )

    with pytest.raises(ValidationError):
        FlowGraph.model_validate(body)


@pytest.mark.parametrize(
    'scope',
    [
        {
            'node_id': 'scope',
            'kind': 'scope',
            'scope_kind': 'nested_flow',
            'runtime_ref': {'agent_id': 'agent-leaf', 'version': 1},
        },
        {
            'node_id': 'scope',
            'kind': 'scope',
            'scope_kind': 'agent',
            'runtime_ref': {'agent_id': 'agent-root', 'version': 1},
            'nested_flow_ref': {'flow_id': 'flow-child', 'version': 1},
        },
    ],
)
def test_flow_graph_rejects_incomplete_or_ambiguous_scope(scope: dict[str, Any]) -> None:
    """Keep Nested Flow pins and direct component scopes unambiguous."""
    body = _minimal_graph()
    body['nodes'][1] = scope

    with pytest.raises(ValidationError):
        FlowGraph.model_validate(body)


def _edges(body: GraphBody) -> list[GraphBody]:
    return cast('list[GraphBody]', body['edges'])


def _resource(node_id: str = 'crm') -> GraphBody:
    return {
        'node_id': node_id,
        'kind': 'resource',
        'relationship': 'capability',
        'component_ref': {'component_id': f'cmp-{node_id}', 'version': 1, 'component_kind': 'tool'},
    }


def _with_resource(*edges: GraphBody) -> GraphBody:
    body = _minimal_graph()
    cast('list[GraphBody]', body['nodes']).append(_resource())
    cast('GraphBody', cast('GraphBody', body['layout'])['node_positions'])['crm'] = {'x': 0, 'y': 0}
    _edges(body).extend(edges)
    return body


def _second_control(body: GraphBody) -> None:
    _edges(body).append(
        {'edge_id': 'again', 'kind': 'control', 'source': 'trigger', 'target': 'scope'}
    )


def _reversed_control(body: GraphBody) -> None:
    _edges(body)[0] = {'edge_id': 'start', 'kind': 'control', 'source': 'scope', 'target': 'output'}


def _second_result(body: GraphBody) -> None:
    _edges(body).append(
        {'edge_id': 'again', 'kind': 'result', 'source': 'scope', 'target': 'output'}
    )


def _result_from_trigger(body: GraphBody) -> None:
    _edges(body)[1] = {
        'edge_id': 'finish',
        'kind': 'result',
        'source': 'trigger',
        'target': 'output',
    }


def _nested_flow_with_component(body: GraphBody) -> None:
    scope = cast('list[GraphBody]', body['nodes'])[1]
    scope['scope_kind'] = 'nested_flow'
    scope['nested_flow_ref'] = {'flow_id': 'flow-child', 'version': 1}


def _nested_flow_without_ref(body: GraphBody) -> None:
    scope = cast('list[GraphBody]', body['nodes'])[1]
    scope['scope_kind'] = 'nested_flow'
    del scope['component_ref']


def _agent_with_nested_ref(body: GraphBody) -> None:
    cast('list[GraphBody]', body['nodes'])[1]['nested_flow_ref'] = {
        'flow_id': 'flow-child',
        'version': 1,
    }


def _swarm_with_agent_component(body: GraphBody) -> None:
    cast('list[GraphBody]', body['nodes'])[1]['scope_kind'] = 'swarm'


TOPOLOGY_RULES: list[tuple[GraphMutation, str]] = [
    (_second_control, 'exactly one trigger-to-scope control edge'),
    (_reversed_control, 'exactly one trigger-to-scope control edge'),
    (_second_result, 'exactly one scope-to-output result edge'),
    (_result_from_trigger, 'exactly one scope-to-output result edge'),
    (_nested_flow_with_component, 'a Nested Flow scope requires only nested_flow_ref'),
    (_nested_flow_without_ref, 'a Nested Flow scope requires only nested_flow_ref'),
    (_agent_with_nested_ref, 'an agent or swarm scope cannot carry nested_flow_ref'),
    (_swarm_with_agent_component, 'scope_kind must match component_ref.component_kind'),
]


@pytest.mark.parametrize(
    ('mutate', 'message'),
    TOPOLOGY_RULES,
    ids=[mutate.__name__.lstrip('_') for mutate, _ in TOPOLOGY_RULES],
)
def test_flow_graph_execution_edges_and_scope_selectors_name_the_broken_rule(
    mutate: GraphMutation,
    message: str,
) -> None:
    """Each execution-edge and scope-selector rule refuses with its own reason."""
    body = _minimal_graph()
    mutate(body)
    with pytest.raises(ValidationError, match=message):
        FlowGraph.model_validate(body)


def test_nested_flow_scope_without_component_is_accepted() -> None:
    """A Nested Flow scope names only its nested flow."""
    body = _minimal_graph()
    _nested_flow_without_ref(body)
    cast('list[GraphBody]', body['nodes'])[1]['nested_flow_ref'] = {
        'flow_id': 'flow-child',
        'version': 1,
    }
    assert FlowGraph.model_validate(body).nodes[1].kind == 'scope'


CAPABILITY = {'edge_id': 'use', 'kind': 'capability', 'source': 'scope', 'target': 'crm'}


@pytest.mark.parametrize(
    ('edges', 'message'),
    [
        ((), 'Every Flow resource requires one root relationship edge'),
        (({**CAPABILITY, 'source': 'trigger'},), 'must match a root resource relationship'),
        (({**CAPABILITY, 'target': 'output'},), 'must match a root resource relationship'),
        (({**CAPABILITY, 'kind': 'knowledge'},), 'must match a root resource relationship'),
        ((CAPABILITY, {**CAPABILITY, 'edge_id': 'use-2'}), 'exactly one incoming relationship'),
    ],
)
def test_flow_resources_need_exactly_one_matching_root_edge(
    edges: tuple[GraphBody, ...],
    message: str,
) -> None:
    """Every resource is reached once, from the scope, by its declared relationship."""
    with pytest.raises(ValidationError, match=message):
        FlowGraph.model_validate(_with_resource(*edges))
    assert FlowGraph.model_validate(_with_resource(CAPABILITY))
