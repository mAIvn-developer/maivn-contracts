"""The immutable hosted launch retains the same message binding as served work."""

import json
from pathlib import Path

from maivn_contracts.scenarios import validate_trigger_launch


def test_hosted_launch_accepts_and_retains_declared_template() -> None:
    """Both the owner JSON schema and Python loader admit a pinned binding."""
    fixture = json.loads(
        (Path(__file__).resolve().parents[2] / 'fixtures/valid_trigger_launches.json').read_text()
    )[0]
    fixture['binding'] = {
        'kind': 'template',
        'messages': ['Notify: {{event.payload.fields.message}}'],
    }
    launch = validate_trigger_launch(fixture)
    assert launch.model_dump(mode='json')['binding'] == fixture['binding']
