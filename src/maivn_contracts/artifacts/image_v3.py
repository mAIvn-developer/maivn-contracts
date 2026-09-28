"""Closed rich raster composition and provider-neutral generation intent."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

from maivn_contracts.artifacts.common_v3 import (
    ArtifactPlanMetadataV3,
    FontSpec,
    HexColor,
    RichArtifactInvariantError,
    RichArtifactModel,
    StructuralId,
)

PixelCoordinate: TypeAlias = Annotated[StrictInt, Field(ge=-40_000_000, le=40_000_000)]
PixelDimension: TypeAlias = Annotated[StrictInt, Field(ge=1, le=40_000_000)]
Opacity: TypeAlias = Annotated[StrictFloat, Field(ge=0.0, le=1.0)]
BlendMode: TypeAlias = Literal['normal', 'multiply', 'screen', 'overlay', 'darken', 'lighten']
_MAX_IMAGE_PIXELS = 40_000_000
_MAX_TOTAL_DECODED_PIXELS = 160_000_000


class ImageCanvasV3(RichArtifactModel):
    """Bounded raster canvas."""

    width_pixels: PixelDimension
    height_pixels: PixelDimension
    background: HexColor
    color_space: Literal['srgb', 'grayscale']


class ImageLayerBaseV3(RichArtifactModel):
    """Shared composition fields."""

    layer_id: StructuralId
    opacity: Opacity
    blend_mode: BlendMode
    mask_input_local_id: StructuralId | None


class ImageTextLayerV3(ImageLayerBaseV3):
    """Runtime-font text layer."""

    layer_type: Literal['text']
    text: Annotated[StrictStr, Field(min_length=1, max_length=16_384)]
    x: PixelCoordinate
    y: PixelCoordinate
    max_width: PixelDimension
    font: FontSpec
    horizontal_alignment: Literal['left', 'center', 'right']
    rotation_degrees: Annotated[StrictFloat, Field(ge=-360.0, le=360.0)]


class ImageSourceLayerV3(ImageLayerBaseV3):
    """Verified source raster with bounded transforms and adjustments."""

    layer_type: Literal['source']
    input_local_id: StructuralId
    x: PixelCoordinate
    y: PixelCoordinate
    width: PixelDimension
    height: PixelDimension
    crop_left: Opacity
    crop_top: Opacity
    crop_right: Opacity
    crop_bottom: Opacity
    rotation_degrees: Annotated[StrictFloat, Field(ge=-360.0, le=360.0)]
    flip_horizontal: StrictBool
    flip_vertical: StrictBool
    brightness: Annotated[StrictFloat, Field(ge=-1.0, le=1.0)]
    contrast: Annotated[StrictFloat, Field(ge=-1.0, le=1.0)]
    saturation: Annotated[StrictFloat, Field(ge=-1.0, le=1.0)]
    sharpness: Annotated[StrictFloat, Field(ge=-1.0, le=1.0)]

    @model_validator(mode='after')
    def _validate_crop(self) -> ImageSourceLayerV3:
        if self.crop_left + self.crop_right >= 1.0 or self.crop_top + self.crop_bottom >= 1.0:
            raise RichArtifactInvariantError
        return self


class ImageShapeLayerV3(ImageLayerBaseV3):
    """Vector-like rasterized shape or annotation."""

    layer_type: Literal['shape']
    shape: Literal['rectangle', 'rounded_rectangle', 'ellipse', 'line', 'polygon', 'callout']
    x: PixelCoordinate
    y: PixelCoordinate
    width: PixelDimension
    height: PixelDimension
    fill: HexColor
    stroke: HexColor
    stroke_width: Annotated[StrictInt, Field(ge=0, le=1_000)]
    points: tuple[tuple[PixelCoordinate, PixelCoordinate], ...] = Field(max_length=128)


class ImageGradientStopV3(RichArtifactModel):
    """One gradient color stop."""

    position: Opacity
    color: HexColor


class ImageGradientLayerV3(ImageLayerBaseV3):
    """Linear or radial gradient layer."""

    layer_type: Literal['gradient']
    gradient_type: Literal['linear', 'radial']
    angle_degrees: Annotated[StrictFloat, Field(ge=-360.0, le=360.0)]
    stops: tuple[ImageGradientStopV3, ...] = Field(min_length=2, max_length=16)

    @model_validator(mode='after')
    def _validate_stops(self) -> ImageGradientLayerV3:
        positions = tuple(stop.position for stop in self.stops)
        if positions != tuple(sorted(positions)) or len(positions) != len(set(positions)):
            raise RichArtifactInvariantError
        return self


ImageLayerV3: TypeAlias = Annotated[
    ImageTextLayerV3 | ImageSourceLayerV3 | ImageShapeLayerV3 | ImageGradientLayerV3,
    Field(discriminator='layer_type'),
]


class ImageOutputV3(RichArtifactModel):
    """Deterministic PNG or JPEG encoder settings."""

    format: Literal['png', 'jpeg']
    transparent: StrictBool
    jpeg_quality: Annotated[StrictInt, Field(ge=1, le=100)] | None
    jpeg_progressive: StrictBool | None
    jpeg_subsampling: Literal['4:4:4', '4:2:2', '4:2:0'] | None
    background: HexColor | None
    strip_metadata: Literal[True]

    @model_validator(mode='after')
    def _validate_format_controls(self) -> ImageOutputV3:
        jpeg_values = (self.jpeg_quality, self.jpeg_progressive, self.jpeg_subsampling)
        if self.format == 'png':
            if any(value is not None for value in jpeg_values):
                raise RichArtifactInvariantError
        elif (
            any(value is None for value in jpeg_values)
            or self.transparent
            or self.background is None
        ):
            raise RichArtifactInvariantError
        return self


class ImageBodyV3(RichArtifactModel):
    """Complete bounded raster composition."""

    canvas: ImageCanvasV3
    layers: tuple[ImageLayerV3, ...] = Field(min_length=1, max_length=1_000)
    output: ImageOutputV3

    @model_validator(mode='after')
    def _validate_layer_ids(self) -> ImageBodyV3:
        layer_ids = tuple(layer.layer_id for layer in self.layers)
        if len(layer_ids) != len(set(layer_ids)):
            raise RichArtifactInvariantError
        return self


class ImageArtifactPlanV3(ArtifactPlanMetadataV3):
    """Closed rich ordinary PNG or JPEG plan."""

    kind: Literal['image']
    output_mime_type: Literal['image/png', 'image/jpeg']
    body: ImageBodyV3

    @model_validator(mode='after')
    def _validate_image_output(self) -> ImageArtifactPlanV3:
        expected_mime = 'image/png' if self.body.output.format == 'png' else 'image/jpeg'
        pixels = self.body.canvas.width_pixels * self.body.canvas.height_pixels
        if expected_mime != self.output_mime_type:
            raise RichArtifactInvariantError
        if (
            self.resource_bounds.max_pixels is None
            or self.resource_bounds.max_pixels < pixels
            or self.resource_bounds.max_pixels > _MAX_IMAGE_PIXELS
            or self.resource_bounds.max_total_decoded_pixels is None
            or self.resource_bounds.max_total_decoded_pixels > _MAX_TOTAL_DECODED_PIXELS
        ):
            raise RichArtifactInvariantError
        return self


class ImageGenerationIntentV1(RichArtifactModel):
    """Provider-neutral generation or edit request."""

    intent_version: Literal['v1']
    operation: Literal['generate', 'edit']
    prompt: Annotated[StrictStr, Field(min_length=1, max_length=16_384)]
    negative_prompt: Annotated[StrictStr, Field(max_length=4_096)] | None
    aspect_ratio: Literal['1:1', '4:3', '3:4', '16:9', '9:16', 'custom']
    width_pixels: Annotated[StrictInt, Field(ge=256, le=8_192)]
    height_pixels: Annotated[StrictInt, Field(ge=256, le=8_192)]
    image_count: Annotated[StrictInt, Field(ge=1, le=4)]
    quality: Literal['standard', 'high']
    style: Literal['natural', 'photorealistic', 'illustration', 'graphic', 'cinematic']
    transparency: StrictBool
    reference_input_local_ids: tuple[StructuralId, ...] = Field(max_length=8)
    edit_source_local_id: StructuralId | None
    edit_mask_local_id: StructuralId | None
    safety_policy: Literal['standard', 'strict']

    @model_validator(mode='after')
    def _validate_operation_inputs(self) -> ImageGenerationIntentV1:
        if self.width_pixels * self.height_pixels > _MAX_IMAGE_PIXELS:
            raise RichArtifactInvariantError
        if self.operation == 'generate':
            if self.edit_source_local_id is not None or self.edit_mask_local_id is not None:
                raise RichArtifactInvariantError
        elif self.edit_source_local_id is None:
            raise RichArtifactInvariantError
        if self.edit_mask_local_id is not None and self.edit_source_local_id is None:
            raise RichArtifactInvariantError
        return self
