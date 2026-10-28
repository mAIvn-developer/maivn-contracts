"""The staff-box boundary accepts only positive, finite page-fraction rectangles."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from maivn_contracts.messages.model import CoverRegion, PIIWhitelistEntry


@pytest.mark.parametrize(
    'bbox',
    [(0, 0, 0, 0.2), (0.9, 0, 0.2, 0.2), (-0.1, 0, 0.1, 0.1), (0, 0, float('nan'), 0.1)],
)
def test_invalid_box_is_refused(bbox: tuple[float, float, float, float]) -> None:
    """A clipped or empty rectangle would falsely promise coverage."""
    with pytest.raises(ValidationError):
        CoverRegion(attachment_id='scan', page=1, bbox=bbox)


def test_free_label_and_box_key_aliases_are_preserved() -> None:
    """Labels describe staff intent without inventing a detector type."""
    region = CoverRegion.model_validate(
        {
            'attachment_id': 'scan',
            'page': 2,
            'box': [0.1, 0.2, 0.3, 0.4],
            'key': 'signature',
            'label': 'signature',
            'description': 'Applicant signature',
        }
    )
    assert region.name == 'signature'
    assert region.label == 'signature'
    assert region.pii_type == 'other'


def test_unredact_requires_a_nonblank_justification() -> None:
    """An exact value alone cannot authorize a suppression."""
    with pytest.raises(ValidationError):
        PIIWhitelistEntry(value='public@example.test', justification='   ')
