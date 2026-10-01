"""Segmentador de páginas: caracteres PDFium → bloques con caja y fuente.

Determinista (ADR-TP-2): sin ML, solo geometría del documento.

1. Escanea los caracteres en orden de lectura (``get_charbox`` +
   ``FPDFText_GetFontSize``, API de posicionamiento de PDFium).
2. Agrupa caracteres en líneas por solapamiento vertical.
3. Agrupa líneas en bloques cuando el hueco vertical es pequeño
   (heuristica: hueco <= 60% de la fuente menor de ambas líneas).
4. Extrae el texto de cada bloque con ``get_text_bounded(l, b, r, t)``,
   con padding para no truncar glifos en los bordes (lección del
   adaptador: los bounds exactos cortan caracteres).
"""

import statistics
from dataclasses import dataclass

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw

# Solapamiento estricto para considerar dos caracteres en la misma línea.
_LINE_OVERLAP_EPSILON = 0.01
# Hueco vertical (como fracción de la fuente menor) que separa bloques.
_BLOCK_GAP_FACTOR = 0.6
# Padding de la caja al pedir texto: evita truncado en los bordes.
_BBOX_PAD = 1.0


@dataclass(frozen=True)
class TextBlock:
    """Bloque de texto con su caja y tamaño de fuente mediano."""

    text: str
    font_size: float
    bbox: tuple[float, float, float, float]  # left, bottom, right, top


@dataclass
class _Line:
    left: float
    bottom: float
    right: float
    top: float
    sizes: list[float]


def segment_page(text_page: pdfium.PdfTextPage) -> list[TextBlock]:
    """Devuelve los bloques de texto de una página, en orden de lectura."""
    lines = _collect_lines(text_page)
    blocks: list[list[_Line]] = _group_lines_into_blocks(lines)
    return [_to_text_block(text_page, block) for block in blocks]


def _collect_lines(text_page: pdfium.PdfTextPage) -> list[_Line]:
    char_count = text_page.count_chars()
    lines: list[_Line] = []
    for index in range(char_count):
        left, bottom, right, top = text_page.get_charbox(index)
        if top <= bottom:
            # Pseudo-caracteres (\r, \n): sin geometría, romperian el
            # cálculo de huecos con su fuente falsa de 1pt.
            continue
        size = pdfium_raw.FPDFText_GetFontSize(text_page.raw, index)
        current = lines[-1] if lines else None
        if current is not None and _overlaps_vertically(current, bottom, top):
            current.left = min(current.left, left)
            current.bottom = min(current.bottom, bottom)
            current.right = max(current.right, right)
            current.top = max(current.top, top)
            current.sizes.append(size)
        else:
            lines.append(
                _Line(
                    left=left, bottom=bottom, right=right, top=top, sizes=[size]
                )
            )
    return lines


def _overlaps_vertically(line: _Line, bottom: float, top: float) -> bool:
    return (
        min(line.top, top) - max(line.bottom, bottom) > _LINE_OVERLAP_EPSILON
    )


def _group_lines_into_blocks(lines: list[_Line]) -> list[list[_Line]]:
    blocks: list[list[_Line]] = []
    for line in lines:
        if blocks and _belongs_to_last_block(blocks[-1][-1], line):
            blocks[-1].append(line)
        else:
            blocks.append([line])
    return blocks


def _belongs_to_last_block(previous: _Line, current: _Line) -> bool:
    gap = previous.bottom - current.top
    smaller_font = min(
        statistics.median(previous.sizes), statistics.median(current.sizes)
    )
    return gap <= _BLOCK_GAP_FACTOR * smaller_font


def _to_text_block(
    text_page: pdfium.PdfTextPage, block: list[_Line]
) -> TextBlock:
    left = min(line.left for line in block)
    bottom = min(line.bottom for line in block)
    right = max(line.right for line in block)
    top = max(line.top for line in block)
    text = text_page.get_text_bounded(
        left - _BBOX_PAD,
        bottom - _BBOX_PAD,
        right + _BBOX_PAD,
        top + _BBOX_PAD,
    )
    sizes = [size for line in block for size in line.sizes]
    return TextBlock(
        text=text,
        font_size=statistics.median(sizes),
        bbox=(left, bottom, right, top),
    )
