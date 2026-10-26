"""Model-call nodes of the session trace: exchanges, usage, timing and legacy spans."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, cast

from maivn_contracts.events._trace_detail import MAX_DETAIL_TEXT, trace_tokens
from maivn_contracts.events._trace_nodes import TraceNode, TraceTokens

if TYPE_CHECKING:
    from maivn_contracts.events.model import Event


def close_terminal_model_exchanges(node: TraceNode) -> None:
    """Keep synthetic/legacy model children consistent with a terminal run."""
    if node.status not in {'completed', 'failed', 'cancelled'} or node.ended_at is None:
        return
    for child in node.children:
        if child.kind != 'model' or child.status != 'running':
            continue
        child.status = node.status
        child.ended_at = node.ended_at
        child.duration_ms = elapsed_ms(child.started_at, child.ended_at)


def finalize_legacy_model_span(node: TraceNode, run_event: Event | None = None) -> None:
    """Infer provider time for reporters that predate explicit model lifecycle events."""
    exchange = next(
        (
            child
            for child in node.children
            if child.kind == 'model'
            and 'turn_index' not in child.detail
            and child.started_at is None
        ),
        None,
    )
    if exchange is None:
        return
    # A prompt placeholder and a selected route do not prove a provider call.
    # Deterministic jobs have both, but no lifecycle event or provider usage.
    # Explicit calls are handled above by turn/call identity, including zero usage.
    if node.tokens is None or not any(
        (
            node.tokens.input_tokens,
            node.tokens.output_tokens,
            node.tokens.cache_read_tokens,
            node.tokens.cache_creation_tokens,
        )
    ):
        exchange.kind = 'working'
        exchange.name = 'Run context'
        exchange.status = node.status
        exchange.started_at = node.started_at
        exchange.ended_at = node.ended_at
        exchange.detail['phase'] = 'request_context'
        return
    routing = next((child for child in node.children if child.kind == 'routing'), None)
    if routing is None or routing.started_at is None:
        return
    start = routing.started_at
    end_node = next(
        (
            child
            for child in node.children
            if child.started_at is not None
            and child.started_at >= start
            and (
                child.kind == 'tool'
                or (child.kind == 'working' and child.detail.get('phase') == 'executing_actions')
            )
        ),
        None,
    )
    ended_at = end_node.started_at if end_node is not None else node.ended_at
    if ended_at is None:
        return
    exchange.name = 'Model call 1' if run_event is None else _model_call_label(run_event, 0)
    exchange.started_at = start
    exchange.ended_at = ended_at
    exchange.duration_ms = elapsed_ms(start, ended_at)
    exchange.status = (
        'completed' if node.status == 'completed' or end_node is not None else 'running'
    )
    if exchange.tokens is None:
        exchange.tokens = node.tokens.model_copy(deep=True)


def fold_model_event(node: TraceNode, event: Event, projected: str) -> bool:
    handlers = {
        'trace.model_stream': _fold_model_stream,
        'trace.model_started': _fold_model_started,
        'trace.model_completed': _fold_model_completed,
    }
    handler = handlers.get(projected)
    if handler is None:
        return False
    handler(node, event)
    return True


def _identified_model_exchange(
    node: TraceNode,
    model_children: list[TraceNode],
    model_call_id: str,
    turn_index: int | None,
) -> TraceNode:
    for child in model_children:
        if child.detail.get('model_call_id') == model_call_id:
            return child
    placeholder = next(
        (
            child
            for child in model_children
            if child.started_at is None and 'model_call_id' not in child.detail
        ),
        None,
    )
    if placeholder is not None:
        placeholder.detail.update(model_call_id=model_call_id, turn_index=turn_index)
        return placeholder
    exchange = TraceNode(
        node_id=f'model--{node.node_id}--call-{model_call_id}',
        kind='model',
        name='Model call',
        status='running',
        detail={'model_call_id': model_call_id, 'turn_index': turn_index},
    )
    node.children.append(exchange)
    return exchange


def _model_exchange(
    node: TraceNode,
    *,
    turn_index: int | None = None,
    model_call_id: str | None = None,
) -> TraceNode:
    model_children = [child for child in node.children if child.kind == 'model']
    if model_call_id is not None:
        return _identified_model_exchange(node, model_children, model_call_id, turn_index)
    if turn_index is not None:
        for child in model_children:
            if child.detail.get('turn_index') == turn_index:
                return child
        if turn_index == 0 and len(model_children) == 1 and model_children[0].started_at is None:
            model_children[0].detail['turn_index'] = turn_index
            return model_children[0]
    elif model_children:
        running = next(
            (child for child in reversed(model_children) if child.status == 'running'),
            None,
        )
        return running or model_children[-1]
    node_id = f'model--{node.node_id}'
    if turn_index is not None and turn_index > 0:
        node_id = f'{node_id}--turn-{turn_index + 1}'
    exchange = TraceNode(
        node_id=node_id,
        kind='model',
        name='Model call' if turn_index is not None else 'Model exchange',
        status='running',
        detail={} if turn_index is None else {'turn_index': turn_index},
    )
    node.children.append(exchange)
    return exchange


def _model_call_label(event: Event, turn_index: int) -> str:
    """Name a model call by where its run sits, relative to that run's parent.

    `Model call {turn + 1}` alone is per-run, so every run's first call is "Model call
    1". Decomposition puts several runs in one tree, and adjacent siblings then render
    the same label - the trace reads as one run calling the model twice.

    A decomposed run is named DEPTH.INDEX, both one-based, so the three subsystem jobs
    of a graph read 1.1, 1.2, 1.3 and a job nested inside the first reads 2.1. The root
    run has no job coordinates and keeps a plain number.

    PARENT-RELATIVE, not globally unique: `job_index` counts within one parent, so two
    grandchildren under different parents are both 2.1. That is a real collision and
    the tree's nesting is what separates them - a globally unique coordinate would have
    to encode the whole path, which is longer than the label it replaces and reads as
    an identifier rather than a position. Sibling confusion was the reported problem;
    cousins were never adjacent.

    The turn is appended only for a run that actually takes more than one, because a
    trailing `.1` on every single-call run is noise that carries nothing.
    """
    turn = turn_index + 1
    if event.job_depth == 0:
        return f'Model call {turn}'
    coordinates = f'{event.job_depth}.{event.job_index + 1}'
    return f'Model call {coordinates}' if turn == 1 else f'Model call {coordinates} turn {turn}'


def _fold_model_started(node: TraceNode, event: Event) -> None:
    turn_index = event.payload.get('turn_index')
    if not isinstance(turn_index, int) or turn_index < 0:
        return
    call_id = event.payload.get('model_call_id')
    exchange = _model_exchange(
        node,
        turn_index=turn_index,
        model_call_id=call_id if isinstance(call_id, str) and call_id else None,
    )
    ordinal = event.payload.get('model_call_ordinal')
    display_ordinal = ordinal if isinstance(ordinal, int) and ordinal >= 0 else turn_index
    # Independent internal calls can restart their local ordinal. Keep their
    # measured identities intact but assign distinct human labels within a run.
    occupied_names = {child.name for child in node.children if child is not exchange}
    while _model_call_label(event, display_ordinal) in occupied_names:
        display_ordinal += 1
    exchange.name = _model_call_label(event, display_ordinal)
    exchange.status = 'running'
    exchange.started_at = event.ts
    exchange.ended_at = None
    exchange.duration_ms = None
    # A model node can exist before it starts: _model_exchange adopts an
    # unstamped placeholder created by an earlier model event, and that
    # placeholder sits wherever it was first appended - ahead of the routing
    # node that chose the model. Ordering by started_at normally corrects
    # that, but only while the two differ. Routing and model-call-started are
    # emitted back to back and land on the same millisecond often enough to
    # see, and a stable sort cannot reorder a tie, so the trace showed a model
    # call above the routing decision that produced it. Moving the node to the
    # point it actually starts makes fold order causal, so the tie resolves
    # correctly instead of exposing where the placeholder happened to sit.
    # Identity, not equality: `list.remove` on pydantic models compares by
    # value, and two unstarted model placeholders are equal by value.
    for index, child in enumerate(node.children):
        if child is exchange:
            del node.children[index]
            break
    node.children.append(exchange)
    routing = next((child for child in reversed(node.children) if child.kind == 'routing'), None)
    routed_model = event.payload.get('model') or (
        None if routing is None else routing.detail.get('model')
    )
    if isinstance(routed_model, str) and routed_model:
        exchange.detail['model'] = routed_model


def _fold_model_completed(node: TraceNode, event: Event) -> None:
    turn_index = event.payload.get('turn_index')
    if not isinstance(turn_index, int) or turn_index < 0:
        return
    call_id = event.payload.get('model_call_id')
    exchange = _model_exchange(
        node,
        turn_index=turn_index,
        model_call_id=call_id if isinstance(call_id, str) and call_id else None,
    )
    status = event.payload.get('model_call_status')
    exchange.status = status if status in {'failed', 'cancelled'} else 'completed'
    error_code = event.payload.get('model_error_code')
    if isinstance(error_code, str) and error_code:
        exchange.detail['error_code'] = error_code
    exchange.ended_at = event.ts
    exchange.duration_ms = (
        event.latency_ms
        if event.latency_ms is not None
        else elapsed_ms(exchange.started_at, event.ts)
    )
    served_model = event.payload.get('model')
    if isinstance(served_model, str) and served_model:
        exchange.detail['model'] = served_model
    if isinstance(event.payload.get('call_usage'), Mapping):
        exchange.tokens = trace_tokens({'usage': event.payload['call_usage']})
        return
    if isinstance(call_id, str) and call_id:
        # Request-local identity requires request-local usage evidence. A run's
        # cumulative counters cannot fill in a missing provider receipt.
        exchange.tokens = None
        return
    cumulative = trace_tokens(event.payload)
    if cumulative is None:
        return
    # Lifecycle counters describe the run so far. Preserve their evidence,
    # while displaying only the current call's contribution. Each run node
    # owns its baseline; nested or concurrent sibling runs never share it.
    exchange.detail['cumulative_usage'] = cumulative.model_dump()
    previous = next(
        (
            child
            for child in node.children
            if child.kind == 'model' and child.detail.get('turn_index') == turn_index - 1
        ),
        None,
    )
    baseline = None if previous is None else previous.detail.get('cumulative_usage')
    if turn_index == 0:
        exchange.tokens = cumulative
    elif isinstance(baseline, dict):
        baseline_counts = cast('dict[str, int]', baseline)
        cumulative_counts = cast('dict[str, int]', cumulative.model_dump())
        counts = {key: value - baseline_counts[key] for key, value in cumulative_counts.items()}
        exchange.tokens = TraceTokens(**counts) if min(counts.values()) >= 0 else None
    else:
        # Missing lifecycle history cannot establish one call's token count.
        exchange.tokens = None


def fold_model_prompt(node: TraceNode, event: Event) -> None:
    trace_input_scope = event.payload.get('trace_input_scope')
    protected_internal_input = event.payload.get('protected_internal_input') is True
    if event.parent_session_id is not None and not (
        trace_input_scope == 'request_context' and protected_internal_input
    ):
        return
    messages = event.payload.get('trace_messages')
    if not isinstance(messages, list | tuple):
        return
    public_messages: list[dict[str, str]] = []
    for item in cast('Iterable[object]', messages):
        if not isinstance(item, Mapping):
            continue
        message = cast('Mapping[str, object]', item)
        role = message.get('role')
        content = message.get('content')
        if role == 'system' or not isinstance(role, str) or not isinstance(content, str):
            continue
        public_messages.append({'role': role, 'content': content[:MAX_DETAIL_TEXT]})
    if not public_messages:
        return
    exchange = _model_exchange(node)
    exchange.detail['prompt'] = public_messages[-1]['content']
    if trace_input_scope == 'request_context':
        exchange.detail['input_scope'] = 'request_context'
        exchange.detail['protected_internal_input'] = True


def _fold_model_stream(node: TraceNode, event: Event) -> None:
    stage = event.payload.get('stage')
    if stage not in {'model_stream', 'final_response_stream'}:
        return
    if event.payload.get('trace_public_response') is not True:
        return
    delta = event.payload.get('content_delta')
    if not isinstance(delta, str) or not delta:
        return
    exchange = _model_exchange(node)
    if (
        'turn_index' in exchange.detail
        and exchange.started_at is not None
        and 'time_to_first_token_ms' not in exchange.detail
    ):
        ttft = elapsed_ms(exchange.started_at, event.ts)
        if ttft is not None:
            exchange.detail['time_to_first_token_ms'] = ttft
    buffered = bool(event.payload.get('buffered_final_response'))
    if buffered and exchange.detail.get('chunk_count'):
        return
    if exchange.started_at is None:
        exchange.started_at = event.ts
    exchange.ended_at = event.ts
    exchange.detail['response'] = (str(exchange.detail.get('response') or '') + delta)[
        :MAX_DETAIL_TEXT
    ]
    exchange.detail['chunk_count'] = int(exchange.detail.get('chunk_count') or 0) + 1
    exchange.detail['streaming'] = not buffered
    exchange.detail['delivery'] = 'buffered replay' if buffered else 'live stream'


def fold_model_final(node: TraceNode, event: Event) -> None:
    if event.payload.get('trace_public_response') is not True:
        return
    message = event.payload.get('trace_message')
    if not isinstance(message, Mapping):
        return
    content = cast('Mapping[str, object]', message).get('content')
    if not isinstance(content, str) or not content:
        return
    exchange = _model_exchange(node)
    exchange.started_at = exchange.started_at or event.ts
    if 'turn_index' not in exchange.detail:
        exchange.ended_at = event.ts
    exchange.status = 'completed'
    exchange.detail['response'] = content[:MAX_DETAIL_TEXT]
    exchange.detail.setdefault('chunk_count', 0)
    exchange.detail.setdefault('streaming', False)


def elapsed_ms(started_at: str | None, ended_at: str | None) -> int | None:
    if started_at is None or ended_at is None:
        return None
    try:
        started = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
        ended = datetime.fromisoformat(ended_at.replace('Z', '+00:00'))
    except ValueError:
        return None
    return max(0, round((ended - started).total_seconds() * 1000))


__all__ = [
    'close_terminal_model_exchanges',
    'elapsed_ms',
    'finalize_legacy_model_span',
    'fold_model_event',
    'fold_model_final',
    'fold_model_prompt',
]
