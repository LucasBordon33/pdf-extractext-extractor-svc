"""Tests del pipeline de conversión a Markdown (ISSUE-006, ADR-TP-2).

Tres niveles:
- Segmentación: integración con pdfium real (fixtures con layout).
- Clasificación y ensamblado: unitarios puros, sin librerías.
- Pipeline completo: a traves del adaptador, incluyendo errores.
"""

from io import BytesIO

import pypdfium2 as pdfium
import pytest

from adapters.extractors.pdf_extractor import PdfTextExtractor
from adapters.markdown.block_classifier import ClassifiedBlock, classify_blocks
from adapters.markdown.markdown_builder import build_document, build_page_markdown
from adapters.markdown.page_segmenter import TextBlock, segment_page
from core.exceptions import CorruptFileError, EmptyExtractionError
from tests.fixtures.pdf_factory import blank_pdf, pdf_with_layout, pdf_with_text

LAYOUT_LINES = (
    ("Titulo Grande", 24, 52),
    ("cuerpo normal", 12, 30),
    ("- item uno", 12, 6),
)
LAYOUT_PDF = pdf_with_layout(*LAYOUT_LINES)


def block(text: str, font_size: float = 12.0) -> TextBlock:
    return TextBlock(text=text, font_size=font_size, bbox=(0.0, 0.0, 100.0, 10.0))


def textpage_of(pdf: bytes) -> tuple:
    document = pdfium.PdfDocument(BytesIO(pdf))
    page = document[0]
    return document, page, page.get_textpage()


class TestSegmentation:
    def test_single_line_pdf_yields_one_block(self):
        document, page, text_page = textpage_of(pdf_with_text("solo una linea"))
        try:
            blocks = segment_page(text_page)
        finally:
            text_page.close()
            page.close()
            document.close()
        assert len(blocks) == 1
        assert blocks[0].text.strip() == "solo una linea"
        assert blocks[0].font_size == pytest.approx(12.0)
        assert len(blocks[0].bbox) == 4

    def test_layout_pdf_yields_block_per_text_group(self):
        document, page, text_page = textpage_of(LAYOUT_PDF)
        try:
            blocks = segment_page(text_page)
        finally:
            text_page.close()
            page.close()
            document.close()
        assert [b.text.strip() for b in blocks] == [
            "Titulo Grande",
            "cuerpo normal",
            "- item uno",
        ]
        assert [b.font_size for b in blocks] == pytest.approx([24.0, 12.0, 12.0])

    def test_multiline_paragraph_stays_one_block(self):
        pdf = pdf_with_layout(("linea uno", 12, 52), ("linea dos", 12, 38))
        document, page, text_page = textpage_of(pdf)
        try:
            blocks = segment_page(text_page)
        finally:
            text_page.close()
            page.close()
            document.close()
        assert len(blocks) == 1
        assert "linea uno" in blocks[0].text
        assert "linea dos" in blocks[0].text


class TestClassification:
    def test_heading_by_relative_font_size(self):
        classified = classify_blocks(
            [
                block("Titulo", 24.0),
                block("Seccion", 18.0),
                block("parrafo", 12.0),
                block("otro", 12.0),
            ]
        )
        assert [(c.kind, c.level) for c in classified] == [
            ("heading", 1),
            ("heading", 2),
            ("paragraph", 0),
        ]
        assert classified[2].text == "parrafo otro"

    def test_heading_third_level_cap(self):
        classified = classify_blocks(
            [
                block("A", 30.0),
                block("B", 24.0),
                block("C", 18.0),
                block("d", 12.0),
                block("e", 12.0),
                block("f", 12.0),
            ]
        )
        levels = [c.level for c in classified if c.kind == "heading"]
        assert levels == [1, 2, 3]

    def test_long_text_is_not_heading_even_with_big_font(self):
        classified = classify_blocks(
            [block("x" * 130, 24.0), block("y", 12.0), block("z", 12.0)]
        )
        assert classified[0].kind == "paragraph"

    def test_uniform_font_size_has_no_headings(self):
        classified = classify_blocks([block("solo", 12.0), block("parrafos", 12.0)])
        assert all(c.kind == "paragraph" for c in classified)

    @pytest.mark.parametrize(
        ("raw", "item"),
        [
            ("- uno", "uno"),
            ("• dos", "dos"),
            ("* tres", "tres"),
            ("1. cuatro", "cuatro"),
            ("a) cinco", "cinco"),
            ("i. seis", "seis"),
        ],
    )
    def test_list_markers_normalize_to_dash(self, raw, item):
        classified = classify_blocks([block(raw)])
        assert classified[0].kind == "list"
        assert classified[0].text == item

    def test_consecutive_paragraphs_merge(self):
        classified = classify_blocks([block("uno"), block("dos")])
        assert len(classified) == 1
        assert classified[0].kind == "paragraph"
        assert classified[0].text == "uno dos"

    def test_whitespace_blocks_are_discarded(self):
        classified = classify_blocks([block("   \n  "), block("real")])
        assert [c.text for c in classified] == ["real"]

    def test_utf16_bom_is_stripped(self):
        classified = classify_blocks([block("﻿hola")])
        assert classified[0].text == "hola"


class TestBuilder:
    def test_page_markdown_renders_each_kind(self):
        md = build_page_markdown(
            [
                ClassifiedBlock(kind="heading", level=1, text="Titulo"),
                ClassifiedBlock(kind="paragraph", level=0, text="cuerpo"),
                ClassifiedBlock(kind="list", level=0, text="item"),
            ]
        )
        assert md == "# Titulo\n\ncuerpo\n\n- item"

    def test_document_joins_pages_with_separator(self):
        assert build_document(["uno", "dos"]) == "uno\n\n---\n\ndos"

    def test_single_page_has_no_separator(self):
        assert build_document(["solo"]) == "solo"

    def test_empty_pages_are_skipped(self):
        assert build_document(["", "real", "  "]) == "real"

    def test_final_cleanup_collapses_newlines_and_trailing_spaces(self):
        md = build_page_markdown(
            [ClassifiedBlock(kind="paragraph", level=0, text="uno\n\n\n\ndos   ")]
        )
        assert md == "uno\n\ndos"

    def test_final_cleanup_normalizes_crlf(self):
        md = build_page_markdown(
            [ClassifiedBlock(kind="paragraph", level=0, text="uno\r\ndos")]
        )
        assert "uno\ndos" in md

    def test_final_cleanup_decodes_html_entities(self):
        md = build_page_markdown(
            [ClassifiedBlock(kind="paragraph", level=0, text="a & b <c>")]
        )
        assert "a & b <c>" in md


class TestPipelineIntegration:
    @pytest.fixture
    def extractor(self):
        return PdfTextExtractor()

    def test_layout_pdf_produces_markdown_structure(self, extractor):
        result = extractor.extract(LAYOUT_PDF, "layout.pdf")
        assert "# Titulo Grande" in result.markdown
        assert "cuerpo normal" in result.markdown
        assert "- item uno" in result.markdown
        assert result.page_count == 1
        assert result.pages_processed == 1
        assert result.duration_ms >= 0.0

    def test_multipage_document_uses_page_separator(self, extractor):
        result = extractor.extract(pdf_with_text("uno", "dos"), "multi.pdf")
        assert result.markdown == "uno\n\n---\n\ndos"

    def test_scanned_pdf_raises_empty_extraction_error(self, extractor):
        with pytest.raises(EmptyExtractionError):
            extractor.extract(blank_pdf(), "escaneado.pdf")

    def test_corrupt_pdf_raises_corrupt_file_error(self, extractor):
        with pytest.raises(CorruptFileError):
            extractor.extract(b"esto no es un pdf", "corrupto.pdf")
