"""Producer requests reject unsafe, ambiguous and unbounded input before IO."""

import pytest
from pydantic import ValidationError

from maivn_contracts.scenarios.producers import (
    ArmSLATimerRequest,
    ConversationReplyRequest,
    SatisfySLATimerRequest,
)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf')])
def test_producer_json_numbers_are_finite(value: float) -> None:
    """Postgres JSON cannot represent non-finite numbers."""
    with pytest.raises(ValidationError):
        ArmSLATimerRequest(instance_key='order:1', payload={'nested': [value]})


@pytest.mark.parametrize('field', ['deadline_seconds', 'started_at', 'project_id', 'trigger_id'])
def test_arm_time_identity_and_deadline_are_server_owned(field: str) -> None:
    """A caller cannot override the scenario or timer timing."""
    with pytest.raises(ValidationError):
        ArmSLATimerRequest.model_validate({'instance_key': 'order:1', field: 'override'})


def test_keys_and_utf8_body_bounds() -> None:
    """Canonical IDs allow punctuation but refuse path separators and overlong content."""
    assert ArmSLATimerRequest(instance_key='A' + '.:_-' * 49).instance_key.startswith('A')
    for key in ['../x', 'a/b', 'a' * 201, '']:
        with pytest.raises(ValidationError):
            ArmSLATimerRequest(instance_key=key)
    with pytest.raises(ValidationError):
        SatisfySLATimerRequest(evidence={'large': '😀' * 65536})
    with pytest.raises(ValidationError):
        ConversationReplyRequest(conversation_key='conversation', reply_id=' ', content='message')
    with pytest.raises(ValidationError):
        ConversationReplyRequest(
            conversation_key='conversation', reply_id='id', content='x' * 65537
        )
