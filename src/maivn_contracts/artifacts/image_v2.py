"""Closed v2 image layers, operations and the image plan body."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field, StrictInt, StrictStr, model_validator

from maivn_contracts.artifacts.plan_inputs import (
    STRUCTURAL_ID_PATTERN,
    RedactedArtifactPayload,
)
from maivn_contracts.artifacts.primitives import (
    MAX_IMAGE_PIXELS,
    ArtifactRefInvariantError,
    ClosedModel,
)

__all__ = [
    'ImageAnnotateOperationV2',
    'ImageCanvasV2',
    'ImageColorConvertOperationV2',
    'ImageCompositeOperationV2',
    'ImageCoordinate',
    'ImageCropOperationV2',
    'ImageEncodeOperationV2',
    'ImageInputRasterLayerV2',
    'ImageLayerV2',
    'ImageOpacity',
    'ImageOperationV2',
    'ImagePixels',
    'ImagePlanBodyV2',
    'ImageRGBHex',
    'ImageResizeOperationV2',
    'ImageRotateOperationV2',
    'ImageShapeLayerV2',
    'ImageTextLayerV2',
]

ImagePixels: TypeAlias = Annotated[StrictInt, Field(ge=1, le=40_000_000)]
ImageCoordinate: TypeAlias = Annotated[StrictInt, Field(ge=0, le=40_000_000)]
ImageOpacity: TypeAlias = Annotated[StrictInt, Field(ge=0, le=1000)]
ImageRGBHex: TypeAlias = Annotated[StrictStr, Field(pattern=r'^[0-9A-F]{6}$')]


class ImageCanvasV2(ClosedModel):
    """Bounded deterministic raster canvas."""

    width_pixels: ImagePixels
    height_pixels: ImagePixels
    color_space: Literal['srgb', 'grayscale']

    @model_validator(mode='after')
    def _validate_pixel_area(self) -> ImageCanvasV2:
        if self.width_pixels * self.height_pixels > MAX_IMAGE_PIXELS:
            raise ArtifactRefInvariantError
        return self


class ImageInputRasterLayerV2(ClosedModel):
    """One immutable raster input placed on the canvas."""

    layer_type: Literal['input_raster']
    layer_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    input_local_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    x_pixels: ImageCoordinate
    y_pixels: ImageCoordinate
    width_pixels: ImagePixels
    height_pixels: ImagePixels
    opacity_per_mille: ImageOpacity


class ImageTextLayerV2(ClosedModel):
    """Redacted text annotation with a closed character presentation."""

    layer_type: Literal['text']
    layer_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    x_pixels: ImageCoordinate
    y_pixels: ImageCoordinate
    max_width_pixels: ImagePixels
    font_family: Annotated[StrictStr, Field(min_length=1, max_length=128)]
    font_size_pixels: Annotated[StrictInt, Field(ge=1, le=1024)]
    color_rgb_hex: ImageRGBHex
    payload: RedactedArtifactPayload


class ImageShapeLayerV2(ClosedModel):
    """Closed geometric annotation without arbitrary vector programs."""

    layer_type: Literal['shape']
    layer_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    shape: Literal['rectangle', 'ellipse', 'line']
    x_pixels: ImageCoordinate
    y_pixels: ImageCoordinate
    width_pixels: ImagePixels
    height_pixels: ImagePixels
    fill_rgb_hex: ImageRGBHex
    opacity_per_mille: ImageOpacity
    stroke_rgb_hex: ImageRGBHex
    stroke_width_pixels: Annotated[StrictInt, Field(ge=0, le=1024)]


ImageLayerV2: TypeAlias = Annotated[
    ImageInputRasterLayerV2 | ImageTextLayerV2 | ImageShapeLayerV2,
    Field(discriminator='layer_type'),
]


class ImageCropOperationV2(ClosedModel):
    """Crop the materialized canvas to one bounded rectangle."""

    operation_type: Literal['crop']
    operation_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    x_pixels: ImageCoordinate
    y_pixels: ImageCoordinate
    width_pixels: ImagePixels
    height_pixels: ImagePixels


class ImageResizeOperationV2(ClosedModel):
    """Resize the materialized canvas with one closed filter."""

    operation_type: Literal['resize']
    operation_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    width_pixels: ImagePixels
    height_pixels: ImagePixels
    filter: Literal['nearest', 'bilinear', 'bicubic', 'lanczos']


class ImageRotateOperationV2(ClosedModel):
    """Rotate the materialized canvas by a lossless right angle."""

    operation_type: Literal['rotate']
    operation_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    degrees: Literal[90, 180, 270]


class ImageCompositeOperationV2(ClosedModel):
    """Composite a closed ordered set of declared layers."""

    operation_type: Literal['composite']
    operation_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    layer_ids: tuple[Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)], ...] = Field(
        min_length=1,
        max_length=1000,
    )


class ImageAnnotateOperationV2(ClosedModel):
    """Apply one declared annotation layer."""

    operation_type: Literal['annotate']
    operation_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    layer_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]


class ImageColorConvertOperationV2(ClosedModel):
    """Convert the canvas to one closed output color space."""

    operation_type: Literal['color_convert']
    operation_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    color_space: Literal['srgb', 'grayscale']


class ImageEncodeOperationV2(ClosedModel):
    """Encode the final canvas to one supported immutable format."""

    operation_type: Literal['encode']
    operation_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    mime_type: Literal['image/png', 'image/jpeg']
    quality: Annotated[StrictInt, Field(ge=1, le=100)]


ImageOperationV2: TypeAlias = Annotated[
    ImageCropOperationV2
    | ImageResizeOperationV2
    | ImageRotateOperationV2
    | ImageCompositeOperationV2
    | ImageAnnotateOperationV2
    | ImageColorConvertOperationV2
    | ImageEncodeOperationV2,
    Field(discriminator='operation_type'),
]


class ImagePlanBodyV2(ClosedModel):
    """Closed bounded raster layer graph and deterministic operation sequence."""

    canvas: ImageCanvasV2
    layers: tuple[ImageLayerV2, ...] = Field(min_length=1, max_length=1000)
    operations: tuple[ImageOperationV2, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode='after')
    def _validate_graph(self) -> ImagePlanBodyV2:
        layer_ids = tuple(layer.layer_id for layer in self.layers)
        operation_ids = tuple(operation.operation_id for operation in self.operations)
        fragment_ids = tuple(
            fragment.structural_id
            for layer in self.layers
            if isinstance(layer, ImageTextLayerV2)
            for fragment in layer.payload.fragments
        )
        identifiers = (*layer_ids, *operation_ids, *fragment_ids)
        if len(identifiers) != len(set(identifiers)):
            raise ArtifactRefInvariantError
        layer_id_set = set(layer_ids)
        for operation in self.operations:
            if isinstance(operation, ImageCompositeOperationV2):
                if len(operation.layer_ids) != len(set(operation.layer_ids)) or not set(
                    operation.layer_ids,
                ).issubset(layer_id_set):
                    raise ArtifactRefInvariantError
            elif isinstance(operation, ImageAnnotateOperationV2) and operation.layer_id not in (
                layer_id_set
            ):
                raise ArtifactRefInvariantError
        if not isinstance(self.operations[-1], ImageEncodeOperationV2):
            raise ArtifactRefInvariantError
        return self

    def structural_ids(self) -> tuple[str, ...]:
        """Return every structural identifier in the image body."""
        return (
            *(layer.layer_id for layer in self.layers),
            *(operation.operation_id for operation in self.operations),
            *(
                fragment.structural_id
                for layer in self.layers
                if isinstance(layer, ImageTextLayerV2)
                for fragment in layer.payload.fragments
            ),
        )

    def used_input_local_ids(self) -> frozenset[str]:
        """Return immutable raster inputs consumed by the layer graph."""
        return frozenset(
            layer.input_local_id
            for layer in self.layers
            if isinstance(layer, ImageInputRasterLayerV2)
        )
