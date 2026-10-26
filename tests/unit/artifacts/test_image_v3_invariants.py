# pyright: strict
"""Invariants of rich V3 raster plans and provider-neutral generation intents."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from maivn_contracts.artifacts.image_v3 import ImageArtifactPlanV3, ImageGenerationIntentV1

MAX_PIXELS = 40_000_000
MAX_TOTAL_DECODED_PIXELS = 160_000_000


def _source_layer(**overrides: object) -> dict[str, Any]:
    layer: dict[str, Any] = {
        'layer_type': 'source',
        'layer_id': 'photo',
        'opacity': 1.0,
        'blend_mode': 'normal',
        'mask_input_local_id': None,
        'input_local_id': 'photo_input',
        'x': 0,
        'y': 0,
        'width': 800,
        'height': 600,
        'crop_left': 0.25,
        'crop_top': 0.0,
        'crop_right': 0.25,
        'crop_bottom': 0.5,
        'rotation_degrees': 0.0,
        'flip_horizontal': False,
        'flip_vertical': False,
        'brightness': 0.0,
        'contrast': 0.0,
        'saturation': 0.0,
        'sharpness': 0.0,
    }
    layer.update(overrides)
    return layer


def _gradient_layer(*positions: float) -> dict[str, Any]:
    return {
        'layer_type': 'gradient',
        'layer_id': 'sky',
        'opacity': 1.0,
        'blend_mode': 'normal',
        'mask_input_local_id': None,
        'gradient_type': 'linear',
        'angle_degrees': 0.0,
        'stops': [{'position': position, 'color': '#000000FF'} for position in positions],
    }


PNG_OUTPUT: dict[str, Any] = {
    'format': 'png',
    'transparent': True,
    'jpeg_quality': None,
    'jpeg_progressive': None,
    'jpeg_subsampling': None,
    'background': None,
    'strip_metadata': True,
}
JPEG_OUTPUT: dict[str, Any] = {
    'format': 'jpeg',
    'transparent': False,
    'jpeg_quality': 90,
    'jpeg_progressive': True,
    'jpeg_subsampling': '4:2:0',
    'background': '#FFFFFFFF',
    'strip_metadata': True,
}


def _plan(
    *,
    layers: list[dict[str, Any]] | None = None,
    output: dict[str, Any] | None = None,
    mime: str = 'image/png',
    bounds: dict[str, object] | None = None,
) -> dict[str, Any]:
    return {
        'schema_version': 'v3',
        'kind': 'image',
        'logical_output_name': 'poster',
        'custody_request': 'ordinary',
        'input_refs': [],
        'renderer_profile': 'rich_image_v3',
        'renderer_min_version': '3.0.0',
        'output_mime_type': mime,
        'validation_profile': 'rich_image_v3',
        'disposition': 'final',
        'retention_request': {'retention_class': 'demo'},
        'resource_bounds': bounds
        or {
            'max_output_bytes': 1_000_000,
            'max_pixels': 1_000_000,
            'max_total_decoded_pixels': 2_000_000,
        },
        'body': {
            'canvas': {
                'width_pixels': 1000,
                'height_pixels': 1000,
                'background': '#000000FF',
                'color_space': 'srgb',
            },
            'layers': layers or [_gradient_layer(0.0, 1.0)],
            'output': output or PNG_OUTPUT,
        },
    }


def test_plan_accepts_png_and_jpeg_outputs_with_their_own_controls() -> None:
    """PNG carries no JPEG controls; JPEG carries all of them, opaque, with a background."""
    assert ImageArtifactPlanV3.model_validate(_plan()).body.output.format == 'png'
    jpeg = ImageArtifactPlanV3.model_validate(_plan(output=JPEG_OUTPUT, mime='image/jpeg'))
    assert jpeg.body.output.jpeg_quality == JPEG_OUTPUT['jpeg_quality']


@pytest.mark.parametrize(
    ('output', 'mime'),
    [
        ({**PNG_OUTPUT, 'jpeg_quality': 90}, 'image/png'),
        ({**PNG_OUTPUT, 'jpeg_subsampling': '4:4:4'}, 'image/png'),
        ({**JPEG_OUTPUT, 'jpeg_quality': None}, 'image/jpeg'),
        ({**JPEG_OUTPUT, 'jpeg_progressive': None}, 'image/jpeg'),
        ({**JPEG_OUTPUT, 'transparent': True}, 'image/jpeg'),
        ({**JPEG_OUTPUT, 'background': None}, 'image/jpeg'),
        (JPEG_OUTPUT, 'image/png'),
        (PNG_OUTPUT, 'image/jpeg'),
    ],
)
def test_plan_refuses_mismatched_encoder_controls_or_mime(
    output: dict[str, Any],
    mime: str,
) -> None:
    """Encoder controls must match the format, and the format must match the MIME type."""
    with pytest.raises(ValidationError):
        ImageArtifactPlanV3.model_validate(_plan(output=output, mime=mime))


@pytest.mark.parametrize(
    'bounds',
    [
        {'max_output_bytes': 1, 'max_total_decoded_pixels': 2_000_000},
        {'max_output_bytes': 1, 'max_pixels': 999_999, 'max_total_decoded_pixels': 2_000_000},
        {
            'max_output_bytes': 1,
            'max_pixels': MAX_PIXELS + 1,
            'max_total_decoded_pixels': 2_000_000,
        },
        {'max_output_bytes': 1, 'max_pixels': 1_000_000},
        {
            'max_output_bytes': 1,
            'max_pixels': 1_000_000,
            'max_total_decoded_pixels': MAX_TOTAL_DECODED_PIXELS + 1,
        },
    ],
)
def test_plan_pixel_bounds_must_cover_the_canvas_within_platform_limits(
    bounds: dict[str, object],
) -> None:
    """Pixel bounds are required, cover the canvas and stay under the platform maxima."""
    with pytest.raises(ValidationError):
        ImageArtifactPlanV3.model_validate(_plan(bounds=bounds))


def test_plan_pixel_bounds_accept_their_inclusive_edges() -> None:
    """The canvas area and the platform maxima are inclusive."""
    bounds: dict[str, object] = {
        'max_output_bytes': 1,
        'max_pixels': 1_000_000,
        'max_total_decoded_pixels': MAX_TOTAL_DECODED_PIXELS,
    }
    assert ImageArtifactPlanV3.model_validate(_plan(bounds=bounds))
    bounds['max_pixels'] = MAX_PIXELS
    assert ImageArtifactPlanV3.model_validate(_plan(bounds=bounds))


def test_layers_need_unique_ids() -> None:
    """Two layers may not share an id."""
    layers = [_gradient_layer(0.0, 1.0), _source_layer(layer_id='sky')]
    with pytest.raises(ValidationError):
        ImageArtifactPlanV3.model_validate(_plan(layers=layers))


def test_source_layer_crop_must_leave_visible_pixels() -> None:
    """Opposite crops summing below one are accepted; reaching one on either axis fails."""
    assert ImageArtifactPlanV3.model_validate(_plan(layers=[_source_layer()]))
    for overrides in (
        {'crop_left': 0.5, 'crop_right': 0.5},
        {'crop_top': 0.75, 'crop_bottom': 0.25},
    ):
        with pytest.raises(ValidationError):
            ImageArtifactPlanV3.model_validate(_plan(layers=[_source_layer(**overrides)]))


@pytest.mark.parametrize('positions', [(1.0, 0.0), (0.0, 0.5, 0.5), (0.5, 0.25, 1.0)])
def test_gradient_stops_must_strictly_increase(positions: tuple[float, ...]) -> None:
    """Stops are sorted by position and no two share one."""
    with pytest.raises(ValidationError):
        ImageArtifactPlanV3.model_validate(_plan(layers=[_gradient_layer(*positions)]))


def _intent(**overrides: object) -> dict[str, Any]:
    intent: dict[str, Any] = {
        'intent_version': 'v1',
        'operation': 'generate',
        'prompt': 'A quiet harbor at dawn.',
        'negative_prompt': None,
        'aspect_ratio': 'custom',
        'width_pixels': 1024,
        'height_pixels': 1024,
        'image_count': 1,
        'quality': 'standard',
        'style': 'natural',
        'transparency': False,
        'reference_input_local_ids': [],
        'edit_source_local_id': None,
        'edit_mask_local_id': None,
        'safety_policy': 'standard',
    }
    intent.update(overrides)
    return intent


def test_generation_intent_edit_needs_a_source_and_generate_takes_none() -> None:
    """Edits name a source (and optionally a mask); generation names neither."""
    edit = ImageGenerationIntentV1.model_validate(
        _intent(operation='edit', edit_source_local_id='source', edit_mask_local_id='mask'),
    )
    assert edit.edit_mask_local_id == 'mask'
    for overrides in (
        {'operation': 'edit'},
        {'operation': 'edit', 'edit_mask_local_id': 'mask'},
        {'edit_source_local_id': 'source'},
        {'edit_mask_local_id': 'mask'},
    ):
        with pytest.raises(ValidationError):
            ImageGenerationIntentV1.model_validate(_intent(**overrides))


def test_generation_intent_area_is_bounded_inclusively() -> None:
    """Width times height may reach but not exceed the platform pixel maximum."""
    assert ImageGenerationIntentV1.model_validate(_intent(width_pixels=8000, height_pixels=5000))
    with pytest.raises(ValidationError):
        ImageGenerationIntentV1.model_validate(_intent(width_pixels=8000, height_pixels=5001))


def _input_ref(local_id: str, artifact_id: str) -> dict[str, Any]:
    return {
        'local_id': local_id,
        'artifact_id': artifact_id,
        'revision': 1,
        'generation': 1,
        'sha256': 'a' * 64,
        'expected_mime_type': 'image/png',
        'purpose': 'image',
    }


def test_plan_inputs_need_unique_local_ids_and_identities() -> None:
    """Two inputs may share neither a local id nor an exact artifact identity."""
    distinct = _plan()
    distinct['input_refs'] = [_input_ref('one', 'art_1'), _input_ref('two', 'art_2')]
    assert ImageArtifactPlanV3.model_validate(distinct)
    for refs in (
        [_input_ref('one', 'art_1'), _input_ref('one', 'art_2')],
        [_input_ref('one', 'art_1'), _input_ref('two', 'art_1')],
    ):
        plan = _plan()
        plan['input_refs'] = refs
        with pytest.raises(ValidationError):
            ImageArtifactPlanV3.model_validate(plan)
