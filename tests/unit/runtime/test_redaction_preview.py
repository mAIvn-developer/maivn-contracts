"""Approved-copy tickets are part of the shared runtime wire contract."""

from maivn_contracts.runtime import RunConfig, validate_run_config


def test_preview_ticket_survives_shared_wire_validation() -> None:
    """The HTTP boundary accepts a ticket and retains it for intake verification."""
    payload = {'user_id': 'user-1', 'thread_id': 'thread-1', 'redaction_preview_id': 'rpv1_sealed'}
    config = validate_run_config(payload)
    assert config.redaction_preview_id == payload['redaction_preview_id']
    assert config.model_dump(exclude_none=True)['redaction_preview_id'] == 'rpv1_sealed'
    assert 'rpv1_sealed' not in repr(config)


def test_ordinary_config_has_no_approval() -> None:
    """Ordinary serialized requests omit the optional ticket."""
    config = RunConfig(user_id='user-1', thread_id='thread-1')
    assert config.redaction_preview_id is None
    assert 'redaction_preview_id' not in config.model_dump(exclude_none=True)
