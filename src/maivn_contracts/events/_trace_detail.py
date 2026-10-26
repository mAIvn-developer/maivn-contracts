"""What may enter trace-node detail: allowlists, bounds, redaction and placeholders."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any, cast

from maivn_contracts.events._trace_nodes import TraceTokens

if TYPE_CHECKING:
    from maivn_contracts.events._trace_nodes import TraceNode, TraceNodeKind
    from maivn_contracts.events.model import Event

# The routing aspect surfaces WHY a model served the run - the curated subset
# of the model_routing payload users see (traceability directive 2026-07-13).
_ROUTING_DETAIL_KEYS = (
    'planning_requested',
    'planning_tier',
    'planning_reason',
    'planning_auto',
    'mode',
    'pinned',
    'source_profile',
    'profile',
    'complexity',
    'model',
    'chain',
    'selection_policy',
    'fallback_policy',
    'policy_origin',
    'policy_id',
    'adaptation_reason',
    'evidence_status',
    'evidence_digest',
    'evidence_samples',
    'acceptance_rate',
    'acceptance_lower_bound',
    'expected_task_cost',
    'expected_wall_ms',
    'expected_wall_p95_ms',
    'expected_task_cost_ceiling_usd',
    'attempt_id',
    'first_event_ms',
    'first_useful_ms',
    'first_visible_ms',
    'elapsed_ms',
    'usage_status',
    'reasons',
)


# A hook aspect says WHICH developer hook ran and how it ended, never what
# passed through it. Structural only, mirroring how tool and model names are
# already public while their arguments and results are not.
_HOOK_DETAIL_KEYS = ('name', 'stage', 'status', 'target_type')

# A decision step says THAT a decision model ran, which one, for how long and on
# whose behalf - never its question, inputs, choices or verdict (owner ruling
# 2026-10-22). The payload is closed upstream; this allowlist keeps it closed here.
_DECISION_ORIGINS = frozenset({'platform', 'sdk'})

_ASPECT_DETAIL_KEYS = (
    'mode',
    'hit_count',
    'skill_count',
    'insight_count',
    'resource_count',
    'latency_ms',
    'extracted_count',
    'persisted_count',
    'vector_rows',
    'graph_edges',
)

_DOCUMENT_ASPECT_DETAIL_KEYS = {
    'document_analysis_selected': (
        'reason',
        'estimated_document_tokens',
        'estimated_protected_input_tokens',
        'context_ratio',
    ),
    'document_evidence_coverage': (
        'expected_resource_count',
        'packet_count',
        'complete_resource_count',
        'failed_resource_count',
        'unavailable_resource_count',
        'uncertain_resource_count',
        'partial_resource_count',
        'no_evidence_resource_count',
        'gap_resource_count',
        'missing_packet_count',
        'finding_count',
        'gap_count',
        'covered_page_count',
        'covered_section_count',
        'coverage_complete',
        'model_input_tokens',
        'model_output_tokens',
        'navigation_calls',
        'elapsed_ms',
        'budget_exhausted',
    ),
}

_SENSITIVE_DETAIL_KEY_PARTS = (
    'api_key',
    'address',
    'authorization',
    'chain_of_thought',
    'password',
    'phone',
    'private_data',
    'prompt',
    'reasoning',
    'secret',
    'ssn',
    'system_message',
    'system_prompt',
    'token',
    'email',
)

_MAX_DETAIL_DEPTH = 5

_MAX_DETAIL_ITEMS = 50

MAX_DETAIL_TEXT = 2_000

_PRIVATE_PLACEHOLDER_PATTERN = re.compile(
    r'\{_\{([A-Za-z0-9_.-]+)\}_\}|\{\{([A-Za-z0-9_.-]+)\}\}|\{_([A-Za-z0-9_.-]+)_\}',
)


def apply_all_redaction_receipts(node: TraceNode) -> None:
    """Apply receipts after folding so event arrival order cannot restore private values."""
    previous_tool: TraceNode | None = None
    for child in node.children:
        if child.kind == 'tool':
            previous_tool = child
        elif child.kind == 'shield' and previous_tool is not None:
            redacted_keys = child.detail.get('redacted_keys')
            if isinstance(redacted_keys, list):
                keys = {
                    key.strip()
                    for key in cast('list[object]', redacted_keys)
                    if isinstance(key, str) and key.strip()
                }
                # A pause a human answered holds copies of its tool's question and answer.
                for target in [previous_tool] + [
                    pause
                    for pause in node.children
                    if pause.kind == 'interrupt'
                    and pause.detail.get('tool_node_id') == previous_tool.node_id
                ]:
                    target.detail = cast(
                        'dict[str, Any]',
                        _redact_matching_keys(target.detail, keys),
                    )
        apply_all_redaction_receipts(child)


def sanitize_public_text_fields(node: TraceNode) -> None:
    for field in ('prompt', 'response'):
        value = node.detail.get(field)
        if not isinstance(value, str):
            continue
        safe_text, keys = _replace_private_placeholders(value)
        node.detail[field] = safe_text
        if keys:
            node.detail[f'{field}_private_keys'] = keys
    for child in node.children:
        sanitize_public_text_fields(child)


def _replace_private_placeholders(value: str) -> tuple[str, list[str]]:
    keys: list[str] = []

    def replace(match: re.Match[str]) -> str:
        key = next(group for group in match.groups() if group is not None)
        if key not in keys:
            keys.append(key)
        return '[PRIVATE]'

    return _PRIVATE_PLACEHOLDER_PATTERN.sub(replace, value), keys


def curated_error_detail(payload: Mapping[str, Any]) -> dict[str, str]:
    """Retain only bounded, user-facing failure fields in a trace node."""
    detail: dict[str, str] = {}
    for key in ('error_type', 'reason', 'message'):
        value = payload.get(key)
        if isinstance(value, str) and value:
            detail[key] = value[:500]
    return detail


def _document_aspect_detail(event: Event, phase: object) -> dict[str, Any]:
    """Project document-only counters only for their closed document phase."""
    if not isinstance(phase, str):
        return {}
    keys = _DOCUMENT_ASPECT_DETAIL_KEYS.get(phase, ())
    memory_value = event.payload.get('memory')
    if not keys or not isinstance(memory_value, Mapping):
        return {}
    memory_payload = cast('Mapping[str, object]', memory_value)
    return {
        key: _sanitize_detail_value(memory_payload[key]) for key in keys if key in memory_payload
    }


def aspect_detail(  # noqa: C901 - closed projection over the trace aspect vocabulary.
    event: Event,
    kind: TraceNodeKind,
) -> dict[str, Any]:
    if kind == 'hook':
        return {
            key: _sanitize_detail_value(event.payload[key])
            for key in _HOOK_DETAIL_KEYS
            if key in event.payload
        }
    if kind == 'routing':
        return {
            key: _sanitize_detail_value(event.payload[key])
            for key in _ROUTING_DETAIL_KEYS
            if key in event.payload
        }
    detail: dict[str, Any] = {}
    phase = event.payload.get('phase')
    if isinstance(phase, str) and phase:
        detail['phase'] = phase
    for key in _ASPECT_DETAIL_KEYS:
        if key in event.payload:
            detail[key] = _sanitize_detail_value(event.payload[key])
    # Memory-family events nest their counters one level down, under `memory`
    # (see DurableMemoryRetrievalDetails and its resource/extraction siblings),
    # so the top-level sweep above finds nothing and the node collapses to a
    # bare {'phase': 'memory_retrieved'} marker. Every other aspect in the tree
    # carries its numbers; memory was the one that did not, which made
    # "Memory retrieved" the only node users could not learn anything from.
    #
    # Same allowlist, same sanitiser: only the counter keys already declared in
    # _ASPECT_DETAIL_KEYS cross over, so recalled skill and insight CONTENT
    # stays out of the trace. That content is caller-supplied and the trace
    # crosses to staff (see _TENANT_VALUE_KEYS), so counts may travel and text
    # may not. Top-level values win when both are present.
    memory_payload = event.payload.get('memory')
    if isinstance(memory_payload, Mapping):
        memory_detail = cast('Mapping[str, object]', memory_payload)
        for key in _ASPECT_DETAIL_KEYS:
            if key in memory_detail and key not in detail:
                detail[key] = _sanitize_detail_value(memory_detail[key])
    detail.update(_document_aspect_detail(event, phase))
    if kind == 'shield':
        redaction = event.payload.get('redaction')
        if isinstance(redaction, Mapping):
            redaction_detail = cast('Mapping[str, object]', redaction)
            count = redaction_detail.get('redacted_value_count')
            keys = redaction_detail.get('redacted_keys') or redaction_detail.get('inserted_keys')
            if isinstance(count, int) and count >= 0:
                detail['redacted_value_count'] = count
            if isinstance(keys, list | tuple):
                key_values = cast('Iterable[object]', keys)
                detail['redacted_keys'] = sorted(
                    {key.strip() for key in key_values if isinstance(key, str) and key.strip()}
                )
    return detail


def decision_detail(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Project a decision step to exactly its model, duration and origin."""
    detail: dict[str, Any] = {}
    model = payload.get('decision_model')
    if isinstance(model, str) and model:
        detail['model'] = model[:MAX_DETAIL_TEXT]
    duration_ms = payload.get('duration_ms')
    if isinstance(duration_ms, int) and not isinstance(duration_ms, bool) and duration_ms >= 0:
        detail['duration_ms'] = duration_ms
    origin = payload.get('origin')
    if origin in _DECISION_ORIGINS:
        detail['origin'] = origin
    return detail


def apply_redaction_receipt(node: TraceNode, redacted_keys: list[object]) -> None:
    """Remove dynamic private values from the tool immediately preceding its receipt."""
    keys = {key.strip() for key in redacted_keys if isinstance(key, str) and key.strip()}
    if not keys:
        return
    tool = next((child for child in reversed(node.children) if child.kind == 'tool'), None)
    if tool is None:
        return
    tool.detail = cast('dict[str, Any]', _redact_matching_keys(tool.detail, keys))


def _redact_matching_keys(value: object, keys: set[str]) -> object:
    if isinstance(value, Mapping):
        redacted: dict[str, object] = {}
        for raw_key, item in cast('Mapping[object, object]', value).items():
            key = str(raw_key)
            matches = key in keys or any(path.endswith(f'.{key}') for path in keys)
            redacted[key] = '[REDACTED]' if matches else _redact_matching_keys(item, keys)
        return redacted
    if isinstance(value, list | tuple):
        return [_redact_matching_keys(item, keys) for item in cast('Iterable[object]', value)]
    return value


def tool_detail(payload: Mapping[str, Any], *, tool_type: str) -> dict[str, Any]:
    """Return bounded tool arguments after defensive field-level scrubbing."""
    detail: dict[str, Any] = {'tool_type': tool_type}
    tool_call = payload.get('tool_call')
    if not isinstance(tool_call, Mapping):
        return detail
    arguments = cast('Mapping[str, object]', tool_call).get('arguments')
    if not isinstance(arguments, Mapping):
        return detail
    names = cast('Mapping[str, object]', arguments)
    detail.update(
        {
            'argument_names': sorted(str(key) for key in names),
            'arguments': _sanitize_detail_value(names),
        }
    )
    return detail


def tool_completion_detail(payload: Mapping[str, Any], *, failed: bool) -> dict[str, Any]:
    outcome = payload.get('outcome')
    outcome_mapping: Mapping[str, object] = (
        cast('Mapping[str, object]', outcome) if isinstance(outcome, Mapping) else {}
    )
    if failed:
        error = outcome_mapping.get('error', cast('object', payload.get('error')))
        return {'error': _sanitize_detail_value(error)} if error is not None else {}
    result = outcome_mapping.get('result', cast('object', payload.get('result')))
    return {'result': _sanitize_detail_value(result)} if result is not None else {}


def _sanitize_detail_value(value: object, *, depth: int = 0, key: str | None = None) -> object:
    """Bound trace detail and redact fields that can carry secrets or internals."""
    if key is not None and any(part in key.lower() for part in _SENSITIVE_DETAIL_KEY_PARTS):
        sanitized: object = '[REDACTED]'
    elif depth >= _MAX_DETAIL_DEPTH:
        sanitized = '[TRUNCATED]'
    elif value is None or isinstance(value, bool | int | float):
        sanitized = value
    elif isinstance(value, str):
        sanitized = _replace_private_placeholders(value[:MAX_DETAIL_TEXT])[0]
    elif isinstance(value, Mapping):
        items = list(cast('Mapping[object, object]', value).items())[:_MAX_DETAIL_ITEMS]
        sanitized = {
            str(item_key): _sanitize_detail_value(
                item_value,
                depth=depth + 1,
                key=str(item_key),
            )
            for item_key, item_value in items
        }
    elif isinstance(value, list | tuple | set):
        sanitized = [
            _sanitize_detail_value(item, depth=depth + 1)
            for item in list(cast('Iterable[object]', value))[:_MAX_DETAIL_ITEMS]
        ]
    else:
        sanitized = str(value)[:MAX_DETAIL_TEXT]
    return sanitized


def child_run_identity(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Say WHAT KIND of run this is, for runs that are not the root.

    A tool job and a swarm member are both child runs at a job depth, and the trace
    rendered them identically - so a decomposed graph and a fanned-out swarm produced
    the same picture, and neither could be told from the other while reading it.

    Structural only, exactly like tool and model names: which kind of run, which plan
    node cut it, how deep. No arguments, no results, nothing a tenant authored.
    """
    run_config = payload.get('run_config')
    if not isinstance(run_config, Mapping):
        return {}
    config = cast('Mapping[str, object]', run_config)
    identity: dict[str, Any] = {}
    kind = config.get('child_run_kind')
    # WHICH KIND OF SCOPE ran, not just its name. `run_name` returns `agent_id` or
    # `swarm_id` as a bare string and discards which it was, so nothing downstream could
    # tell a swarm root from an agent - counting them once reported a swarm root plus two
    # delegates as three agents, and a trace cannot be grouped by scope without it.
    if kind == 'decision_run':
        # A decision-only run has no agent: it holds only Decision steps.
        identity['scope_type'] = 'decision'
    elif isinstance(config.get('swarm_id'), str) and config.get('swarm_id'):
        identity['scope_type'] = 'swarm'
    elif isinstance(config.get('agent_id'), str) and config.get('agent_id'):
        identity['scope_type'] = 'agent'
    # 'root' carries no information a reader needs - it is the absence of a parent,
    # which the tree already shows.
    if isinstance(kind, str) and kind and kind != 'root':
        identity['child_run_kind'] = kind
    plan_node_id = config.get('plan_node_id')
    if isinstance(plan_node_id, str) and plan_node_id:
        identity['plan_node_id'] = plan_node_id
    depth = config.get('decomposition_depth')
    if isinstance(depth, int):
        identity['decomposition_depth'] = depth
    return identity


def run_name(payload: Mapping[str, Any]) -> str:
    run_config = payload.get('run_config')
    if isinstance(run_config, Mapping):
        config = cast('Mapping[str, object]', run_config)
        for key in ('agent_id', 'swarm_id'):
            value = config.get(key)
            if isinstance(value, str) and value:
                return value
    return 'Run'


def trace_tokens(payload: Mapping[str, Any]) -> TraceTokens | None:
    usage = payload.get('usage')
    if not isinstance(usage, Mapping):
        return None
    counts = cast('Mapping[str, object]', usage)

    def count(key: str) -> int:
        value = counts.get(key)
        return value if isinstance(value, int) and value >= 0 else 0

    return TraceTokens(
        input_tokens=count('input_tokens'),
        output_tokens=count('output_tokens'),
        cache_read_tokens=count('cache_read_input_tokens'),
        cache_creation_tokens=count('cache_creation_input_tokens'),
    )


__all__ = [
    'MAX_DETAIL_TEXT',
    'apply_all_redaction_receipts',
    'apply_redaction_receipt',
    'aspect_detail',
    'child_run_identity',
    'curated_error_detail',
    'decision_detail',
    'run_name',
    'sanitize_public_text_fields',
    'tool_completion_detail',
    'tool_detail',
    'trace_tokens',
]
