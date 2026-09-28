"""Closed rich-artifact v3 contract behavior."""

from __future__ import annotations

import json
from typing import cast

import pytest
from pydantic import TypeAdapter, ValidationError

from maivn_contracts.artifacts import (
    ArtifactKind,
    ArtifactPlan,
    MimeType,
    PresentationSafePreview,
    is_mime_type_valid_for_artifact_kind,
    load_artifact_plan_v3_schema,
    validate_artifact_plan,
)
from maivn_contracts.artifacts.common_v3 import (
    AccessibilityMetadata,
    ArtifactInputRefV3,
    ChartSeries,
    ChartSpec,
    FontSpec,
    HttpsLinkTarget,
    ImagePlacement,
    InternalLinkTarget,
    Paragraph,
    RichText,
    TextRun,
)
from maivn_contracts.artifacts.document_v3 import DocumentArtifactPlanV3
from maivn_contracts.artifacts.image_v3 import ImageArtifactPlanV3, ImageGenerationIntentV1
from maivn_contracts.artifacts.presentation_v3 import PresentationArtifactPlanV3
from maivn_contracts.artifacts.workbook_v3 import (
    WorkbookArtifactPlanV3,
    WorkbookFormulaValueV3,
)

_EXPECTED_FINAL_ARR = 73.0
_EXPECTED_DOCUMENT_BLOCKS = 5
_EXPECTED_GENERATED_IMAGES = 2


def test_presentation_kind_mime_and_safe_preview_are_public_and_closed() -> None:
    """A PPTX has a first-class kind, MIME, and bounded public preview."""
    kind_adapter: TypeAdapter[ArtifactKind] = TypeAdapter(ArtifactKind)
    mime_adapter: TypeAdapter[MimeType] = TypeAdapter(MimeType)

    assert kind_adapter.validate_python('presentation') == 'presentation'
    pptx = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    assert mime_adapter.validate_python(pptx) == pptx
    assert is_mime_type_valid_for_artifact_kind('presentation', pptx)
    assert PresentationSafePreview(kind='presentation', slide_count=12).model_dump() == {
        'kind': 'presentation',
        'slide_count': 12,
    }

    with pytest.raises(ValidationError):
        PresentationSafePreview.model_validate(
            {'kind': 'presentation', 'slide_count': 12, 'provider_id': 'forbidden'}
        )
    with pytest.raises(ValidationError):
        PresentationSafePreview(kind='presentation', slide_count=0)


def test_shared_v3_rich_content_is_bounded_and_provider_neutral() -> None:
    """Shared typography, media, charts, and accessibility stay closed and finite."""
    body = RichText(
        paragraphs=(
            Paragraph(
                paragraph_id='executive_summary',
                runs=(
                    TextRun(
                        text='Northstar Grid grew recurring revenue 31%.',
                        font=FontSpec(
                            family='Aptos',
                            size_points=18.0,
                            weight=700,
                            italic=False,
                            color='#17324D',
                        ),
                        link=HttpsLinkTarget(uri='https://northstar.example/briefing'),
                    ),
                ),
                alignment='left',
            ),
        )
    )
    source = ArtifactInputRefV3(
        local_id='campaign_hero',
        artifact_id='art_campaign_hero',
        revision=2,
        generation=1,
        sha256='a' * 64,
        expected_mime_type='image/png',
        purpose='image',
    )
    placement = ImagePlacement(
        input_local_id=source.local_id,
        width_points=360.0,
        height_points=180.0,
        crop_left=0.0,
        crop_top=0.0,
        crop_right=0.0,
        crop_bottom=0.0,
        rotation_degrees=0.0,
        opacity=1.0,
        alt_text='Solar and storage facilities connected to the Northstar platform.',
    )
    chart = ChartSpec(
        chart_id='arr_growth',
        chart_type='line',
        title='Annual recurring revenue',
        categories=('FY25', 'FY26', 'FY27'),
        series=(ChartSeries(name='ARR', values=(42.0, 55.0, 73.0), color='#35C4B5'),),
        show_legend=True,
        show_data_labels=True,
        alt_text='ARR increases from 42 to 73 million dollars.',
    )
    accessibility = AccessibilityMetadata(
        title='Northstar Grid operating report',
        description='Quarterly performance, outlook, and decisions.',
        language='en-US',
    )

    link = body.paragraphs[0].runs[0].link
    assert isinstance(link, HttpsLinkTarget)
    assert link.uri.startswith('https://')
    assert placement.input_local_id == source.local_id
    assert chart.series[0].values[-1] == _EXPECTED_FINAL_ARR
    assert accessibility.language == 'en-US'
    assert InternalLinkTarget(bookmark_id='financial_outlook').kind == 'internal'

    invalid_payloads = (
        (
            FontSpec,
            {
                'family': 'Aptos',
                'size_points': 12.0,
                'weight': 400,
                'italic': False,
                'color': 'navy',
            },
        ),
        (HttpsLinkTarget, {'uri': 'file:///etc/passwd'}),
        (ArtifactInputRefV3, {**source.model_dump(), 'provider_id': 'forbidden'}),
        (ImagePlacement, {**placement.model_dump(), 'opacity': 1.1}),
        (
            ChartSeries,
            {
                'name': 'too-long',
                'values': tuple(float(i) for i in range(5001)),
                'color': '#000000',
            },
        ),
    )
    for model, payload in invalid_payloads:
        with pytest.raises(ValidationError):
            model.model_validate(payload)


def test_rich_text_rejects_more_than_128_runs_per_paragraph() -> None:
    """One paragraph cannot become an unbounded model-generated payload."""
    with pytest.raises(ValidationError):
        Paragraph(
            paragraph_id='oversized',
            runs=tuple(TextRun(text=str(index)) for index in range(129)),
            alignment='left',
        )


def _envelope(*, kind: str, mime: str, max_pages: int | None = None) -> dict[str, object]:
    bounds: dict[str, object] = {'max_output_bytes': 20_000_000}
    if max_pages is not None:
        bounds['max_pages'] = max_pages
    return {
        'schema_version': 'v3',
        'kind': kind,
        'logical_output_name': f'northstar_{kind}',
        'custody_request': 'ordinary',
        'input_refs': (),
        'renderer_profile': f'rich_{kind}_v3',
        'renderer_min_version': '3.0.0',
        'output_mime_type': mime,
        'validation_profile': f'rich_{kind}_v3',
        'disposition': 'final',
        'retention_request': {'retention_class': 'demo'},
        'resource_bounds': bounds,
    }


def _rich_text(text: str, paragraph_id: str = 'body') -> dict[str, object]:
    return {
        'paragraphs': (
            {
                'paragraph_id': paragraph_id,
                'runs': ({'text': text},),
                'alignment': 'left',
            },
        )
    }


def test_document_v3_accepts_rich_report_and_rejects_active_pdf_content() -> None:
    """Document plans cover designed reports without exposing native payloads."""
    payload: dict[str, object] = {
        **_envelope(kind='document', mime='application/pdf', max_pages=40),
        'body': {
            'theme': {
                'primary': '#17324D',
                'secondary': '#35C4B5',
                'accent': '#F4B942',
                'background': '#FFFFFF',
                'heading_font': 'Aptos Display',
                'body_font': 'Aptos',
            },
            'page': {
                'width_points': 612.0,
                'height_points': 792.0,
                'margins': {'top': 54.0, 'right': 54.0, 'bottom': 54.0, 'left': 54.0},
                'orientation': 'portrait',
                'columns': 1,
            },
            'styles': (
                {
                    'style_id': 'body_style',
                    'font': {
                        'family': 'Aptos',
                        'size_points': 10.5,
                        'weight': 400,
                        'italic': False,
                        'color': '#17324D',
                    },
                    'alignment': 'left',
                    'space_before_points': 0.0,
                    'space_after_points': 6.0,
                    'line_spacing': 1.15,
                },
            ),
            'headers': ({'slot': 'default', 'content': _rich_text('NORTHSTAR GRID', 'header')},),
            'footers': (
                {
                    'slot': 'default',
                    'content': _rich_text('Confidential', 'footer'),
                    'page_number': True,
                    'total_pages': True,
                },
            ),
            'notes': (
                {
                    'note_id': 'method_note',
                    'kind': 'footnote',
                    'content': _rich_text('ARR is annualized recurring revenue.', 'note'),
                },
            ),
            'blocks': (
                {
                    'block_type': 'toc',
                    'block_id': 'contents',
                    'title': 'Contents',
                    'min_level': 1,
                    'max_level': 3,
                },
                {
                    'block_type': 'heading',
                    'block_id': 'summary',
                    'level': 1,
                    'content': _rich_text('Executive summary', 'summary_text'),
                    'bookmark_id': 'executive_summary',
                },
                {
                    'block_type': 'text',
                    'block_id': 'summary_body',
                    'content': _rich_text('Revenue grew while gross margin expanded.', 'summary_p'),
                },
                {
                    'block_type': 'table',
                    'block_id': 'kpi_table',
                    'column_count': 2,
                    'rows': (
                        {
                            'row_id': 'kpi_header',
                            'header': True,
                            'repeat_header': True,
                            'cells': (
                                {
                                    'cell_id': 'metric',
                                    'content': _rich_text('Metric', 'metric_p'),
                                    'column_span': 1,
                                    'row_span': 1,
                                    'fill': '#17324D',
                                },
                                {
                                    'cell_id': 'result',
                                    'content': _rich_text('Result', 'result_p'),
                                    'column_span': 1,
                                    'row_span': 1,
                                    'fill': '#17324D',
                                },
                            ),
                        },
                    ),
                    'banded_rows': True,
                    'header_rows': 1,
                },
                {
                    'block_type': 'chart',
                    'block_id': 'arr_chart',
                    'chart': {
                        'chart_id': 'arr',
                        'chart_type': 'line',
                        'title': 'ARR',
                        'categories': ('FY25', 'FY26'),
                        'series': ({'name': 'ARR', 'values': (42.0, 55.0), 'color': '#35C4B5'},),
                        'show_legend': False,
                        'show_data_labels': True,
                        'alt_text': 'ARR rises from 42 to 55 million.',
                    },
                    'width_points': 468.0,
                    'height_points': 220.0,
                },
            ),
            'accessibility': {
                'title': 'Northstar Grid Q2 operating report',
                'description': 'Board report and outlook.',
                'language': 'en-US',
            },
            'pdf': {
                'tagged': True,
                'pdfa': '2b',
                'allow_actions': False,
                'include_bookmarks': True,
            },
        },
    }
    plan = DocumentArtifactPlanV3.model_validate(payload)
    assert len(plan.body.blocks) == _EXPECTED_DOCUMENT_BLOCKS
    assert plan.body.pdf is not None
    assert plan.body.pdf.tagged
    assert isinstance(TypeAdapter(ArtifactPlan).validate_python(payload), DocumentArtifactPlanV3)
    wire_payload = cast('dict[str, object]', json.loads(json.dumps(payload)))
    assert isinstance(validate_artifact_plan(wire_payload), DocumentArtifactPlanV3)
    assert load_artifact_plan_v3_schema()['$schema'].endswith('2020-12/schema')

    unsafe_payload = cast('dict[str, object]', json.loads(json.dumps(payload)))
    unsafe_body = cast('dict[str, object]', unsafe_payload['body'])
    unsafe_body['pdf'] = {
        'tagged': True,
        'pdfa': '2b',
        'allow_actions': True,
        'include_bookmarks': True,
    }
    with pytest.raises(ValidationError):
        DocumentArtifactPlanV3.model_validate(unsafe_payload)


def test_workbook_v3_accepts_forecast_and_rejects_unsafe_formulas() -> None:
    """Workbook formulas are allowlisted before they reach an Office package."""
    payload: dict[str, object] = {
        **_envelope(
            kind='spreadsheet',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        ),
        'resource_bounds': {'max_output_bytes': 20_000_000, 'max_sheets': 10, 'max_cells': 20_000},
        'body': {
            'theme': {
                'primary': '#17324D',
                'secondary': '#35C4B5',
                'accent': '#F4B942',
                'font_family': 'Aptos',
            },
            'defined_names': ({'name': 'TaxRate', 'formula': '=Assumptions!$B$2'},),
            'sheets': (
                {
                    'sheet_id': 'forecast',
                    'name': 'Forecast',
                    'visibility': 'visible',
                    'cells': (
                        {
                            'address': 'A1',
                            'value': {'value_type': 'text', 'text': 'Revenue'},
                            'style': {
                                'fill': '#17324D',
                                'font_color': '#FFFFFF',
                                'bold': True,
                                'italic': False,
                                'number_format': 'General',
                                'horizontal_alignment': 'left',
                                'vertical_alignment': 'center',
                                'wrap_text': False,
                            },
                        },
                        {'address': 'B2', 'value': {'value_type': 'number', 'number': 42.0}},
                        {
                            'address': 'C2',
                            'value': {'value_type': 'formula', 'formula': '=B2*(1+TaxRate)'},
                        },
                    ),
                    'column_widths': ({'column': 'A', 'width': 24.0},),
                    'row_heights': ({'row': 1, 'height_points': 24.0},),
                    'merges': (),
                    'groups': (),
                    'freeze_panes': 'B2',
                    'auto_filter': 'A1:C24',
                    'tables': (
                        {
                            'table_id': 'forecast_table',
                            'name': 'ForecastTable',
                            'range': 'A1:C24',
                            'style': 'medium2',
                            'show_totals': True,
                        },
                    ),
                    'validations': (
                        {
                            'validation_id': 'scenario',
                            'range': 'B5:B5',
                            'kind': 'list',
                            'formula1': 'Base,Upside,Downside',
                            'allow_blank': False,
                        },
                    ),
                    'conditional_formats': (
                        {
                            'range': 'B2:C24',
                            'kind': 'color_scale',
                            'operator': None,
                            'formula': None,
                            'color': '#35C4B5',
                        },
                    ),
                    'charts': (),
                    'images': (),
                    'notes': (),
                    'print_setup': {
                        'orientation': 'landscape',
                        'paper_size': 'letter',
                        'fit_to_width': 1,
                        'fit_to_height': 1,
                        'print_area': 'A1:C24',
                        'repeat_rows': '1:1',
                    },
                },
            ),
            'calculation_mode': 'auto',
            'strip_metadata': True,
        },
    }
    plan = WorkbookArtifactPlanV3.model_validate(payload)
    formula_value = plan.body.sheets[0].cells[2].value
    assert isinstance(formula_value, WorkbookFormulaValueV3)
    assert formula_value.formula == '=B2*(1+TaxRate)'

    for unsafe in ('=WEBSERVICE("https://evil")', "='[other.xlsx]Sheet1'!A1", "=cmd|' /C calc'!A0"):
        with pytest.raises(ValidationError):
            WorkbookFormulaValueV3(value_type='formula', formula=unsafe)


def test_presentation_v3_accepts_static_rich_deck_and_rejects_active_content() -> None:
    """Presentation plans model editable static slides only."""
    payload: dict[str, object] = {
        **_envelope(
            kind='presentation',
            mime='application/vnd.openxmlformats-officedocument.presentationml.presentation',
            max_pages=40,
        ),
        'body': {
            'theme': {
                'primary': '#17324D',
                'secondary': '#35C4B5',
                'accent': '#F4B942',
                'background': '#FFFFFF',
                'heading_font': 'Aptos Display',
                'body_font': 'Aptos',
            },
            'slide_size': {'preset': 'wide', 'width_points': None, 'height_points': None},
            'layouts': ({'layout_id': 'hero', 'name': 'Hero', 'background': '#17324D'},),
            'sections': ({'section_id': 'strategy', 'title': 'Strategy'},),
            'slides': (
                {
                    'slide_id': 'launch',
                    'layout_id': 'hero',
                    'section_id': 'strategy',
                    'title': 'Launch the grid intelligence era',
                    'hidden': False,
                    'elements': (
                        {
                            'element_type': 'text',
                            'element_id': 'headline',
                            'bounds': {'x': 48.0, 'y': 54.0, 'width': 624.0, 'height': 96.0},
                            'content': _rich_text('Grid intelligence, delivered.', 'headline_p'),
                            'rotation_degrees': 0.0,
                            'opacity': 1.0,
                            'alt_text': 'Launch headline',
                        },
                        {
                            'element_type': 'shape',
                            'element_id': 'accent_bar',
                            'bounds': {'x': 48.0, 'y': 170.0, 'width': 240.0, 'height': 8.0},
                            'shape': 'rectangle',
                            'fill': '#35C4B5',
                            'line_color': '#35C4B5',
                            'line_width_points': 0.0,
                            'rotation_degrees': 0.0,
                            'opacity': 1.0,
                            'alt_text': 'Decorative accent',
                        },
                    ),
                    'speaker_notes': _rich_text('Pause after the market framing.', 'notes_p'),
                    'show_slide_number': True,
                    'footer': 'Northstar Grid — Launch plan',
                    'transition': 'none',
                },
            ),
            'accessibility': {
                'title': 'Northstar Grid launch deck',
                'description': 'Executive product launch plan.',
                'language': 'en-US',
            },
            'allow_animations': False,
            'allow_embedded_media': False,
            'allow_macros': False,
            'allow_ole': False,
        },
    }
    plan = PresentationArtifactPlanV3.model_validate(payload)
    assert plan.body.slides[0].speaker_notes is not None

    for key in ('allow_animations', 'allow_embedded_media', 'allow_macros', 'allow_ole'):
        unsafe_payload = cast('dict[str, object]', json.loads(json.dumps(payload)))
        unsafe_body = cast('dict[str, object]', unsafe_payload['body'])
        unsafe_body[key] = True
        with pytest.raises(ValidationError):
            PresentationArtifactPlanV3.model_validate(unsafe_payload)


def test_image_v3_and_generation_intent_are_bounded_and_provider_neutral() -> None:
    """Raster composition and routed generation expose intent, never provider handles."""
    payload: dict[str, object] = {
        **_envelope(kind='image', mime='image/png'),
        'resource_bounds': {
            'max_output_bytes': 20_000_000,
            'max_pixels': 10_000_000,
            'max_total_decoded_pixels': 20_000_000,
        },
        'body': {
            'canvas': {
                'width_pixels': 1600,
                'height_pixels': 900,
                'background': '#17324DFF',
                'color_space': 'srgb',
            },
            'layers': (
                {
                    'layer_type': 'gradient',
                    'layer_id': 'sky',
                    'opacity': 1.0,
                    'blend_mode': 'normal',
                    'gradient_type': 'linear',
                    'angle_degrees': 25.0,
                    'stops': (
                        {'position': 0.0, 'color': '#17324DFF'},
                        {'position': 1.0, 'color': '#35C4B5FF'},
                    ),
                    'mask_input_local_id': None,
                },
                {
                    'layer_type': 'text',
                    'layer_id': 'headline',
                    'opacity': 1.0,
                    'blend_mode': 'normal',
                    'text': 'ENERGY, ORCHESTRATED.',
                    'x': 96,
                    'y': 120,
                    'max_width': 1100,
                    'font': {
                        'family': 'Aptos Display',
                        'size_points': 72.0,
                        'weight': 700,
                        'italic': False,
                        'color': '#FFFFFFFF',
                    },
                    'horizontal_alignment': 'left',
                    'rotation_degrees': 0.0,
                    'mask_input_local_id': None,
                },
            ),
            'output': {
                'format': 'png',
                'transparent': True,
                'jpeg_quality': None,
                'jpeg_progressive': None,
                'jpeg_subsampling': None,
                'background': None,
                'strip_metadata': True,
            },
        },
    }
    plan = ImageArtifactPlanV3.model_validate(payload)
    assert plan.body.output.transparent

    intent = ImageGenerationIntentV1(
        intent_version='v1',
        operation='generate',
        prompt='Cinematic renewable energy campus at dawn, no text or logos.',
        negative_prompt='watermarks, lettering, trademarks',
        aspect_ratio='16:9',
        width_pixels=1536,
        height_pixels=864,
        image_count=2,
        quality='high',
        style='photorealistic',
        transparency=False,
        reference_input_local_ids=(),
        edit_source_local_id=None,
        edit_mask_local_id=None,
        safety_policy='standard',
    )
    assert intent.image_count == _EXPECTED_GENERATED_IMAGES
    assert 'provider' not in intent.model_dump_json()
    with pytest.raises(ValidationError):
        ImageGenerationIntentV1.model_validate({**intent.model_dump(), 'provider_id': 'x'})
    with pytest.raises(ValidationError):
        ImageGenerationIntentV1.model_validate({**intent.model_dump(), 'operation': 'edit'})
