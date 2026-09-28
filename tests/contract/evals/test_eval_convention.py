# pyright: strict
"""Contract tests for import-free eval harness adoption."""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType
    from typing import Any

EVALS_DIR = Path(__file__).resolve().parents[3] / 'evals'

EXPECTED_OUTPUTS = {
    'agent_registry_eval.py': [
        'PASS deployed-agent registry eval',
        'records_validated=4',
        'version_1_immutability=byte-identical',
        'preview_messages=Case case-1001 for ada@example.com.|Priority: high',
        'note=local preview only; authoritative template rendering is server-side',
    ],
    'message_roundtrip_eval.py': [
        'PASS owned message roundtrip eval',
        'messages_validated=3',
        'placeholder_convention={_{patient_name}_}',
        'generic_literal_detected=<GENERIC>',
        'redacted_attachment_floor=documented-secure',
    ],
    'resource_policy_eval.py': [
        'PASS resource policy eval',
        'plain_bare_attachment_tier=direct',
        'plain_processing_records=0',
        'redacted_attachment_floor=secure',
        'indexed_downgrade_rejected=true',
        'secure_states=pending,processing,ready',
        'artifacts=redacted_markdown,sidecar_map',
        'version_stamps=extractor,ocr,model,redaction,policy',
    ],
    'roundtrip_eval.py': [
        'PASS canonical event roundtrip eval',
        'events_validated=6',
        (
            'canvas_projection=trigger.fired,agent.thinking,agent.tool_selected,'
            'tool.dispatch_started,tool.dispatch_completed,session.completed'
        ),
        (
            'webhook_projection=session.started,checkpoint.created,checkpoint.created,'
            'tool.executed,tool.executed,session.completed'
        ),
    ],
    'run_protocol_eval.py': [
        'PASS run protocol eval',
        'thread_id=thr-eval-001',
        'run_id=run-eval-001',
        'stream_parts=3',
        'nested_custom_parts=1',
        'final_status=completed',
    ],
    'trigger_lifecycle_eval.py': [
        'PASS trigger lifecycle eval',
        'scenario_validated=2',
        'file_output_binding=validated',
        'trigger_validated=1',
        'fire_states_validated=pending,claimed,completed',
        'invocation_validated=1',
        'canonical_event_lineage_validated=1',
    ],
    'tools_contract_eval.py': [
        'PASS tools contract eval',
        'tool_specs_validated=function,mcp',
        'tool_call_validated=call-lookup-001',
        'ok_outcome_artifacts=1',
        'error_outcome_retryable=true',
        'round_trip=byte-stable',
    ],
}


def _load_eval_module(filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        filename.removesuffix('.py'),
        EVALS_DIR / filename,
    )
    if spec is None or spec.loader is None:
        message = f'could not load spec for {filename}'
        raise AssertionError(message)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_eval_modules_expose_import_free_run_eval_result_shape() -> None:
    """Expose a harness-compatible mapping without importing the harness package."""
    for filename in sorted(EXPECTED_OUTPUTS):
        module = _load_eval_module(filename)
        raw_run_eval = getattr(module, 'run_eval', None)
        assert callable(raw_run_eval), filename
        run_eval = cast('Callable[[], object]', raw_run_eval)

        raw_result = run_eval()
        assert isinstance(raw_result, Mapping), filename
        result = cast('Mapping[str, Any]', raw_result)

        assert isinstance(result['name'], str)
        assert result['status'] == 'pass'
        assert result['grade'] in {'A', 'B', 'C', 'D', 'F'}
        assert isinstance(result['metrics'], Mapping)
        assert isinstance(result['details'], str)
        assert isinstance(result['artifacts'], list)
        assert 'ts' in result


def test_standalone_eval_output_stays_identical() -> None:
    """Keep thin __main__ behavior and output unchanged while adding run_eval."""
    for filename, expected_lines in sorted(EXPECTED_OUTPUTS.items()):
        module = _load_eval_module(filename)
        stdout = StringIO()

        raw_main = getattr(module, 'main', None)
        assert callable(raw_main), filename
        main = cast('Callable[[], int]', raw_main)

        with redirect_stdout(stdout):
            exit_code = main()

        assert exit_code == 0, filename
        assert stdout.getvalue().splitlines() == expected_lines
