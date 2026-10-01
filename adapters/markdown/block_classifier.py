"""Clasificador de bloques: heurísticas puras y deterministas (ADR-TP-2).

Reglas:

- **Encabezado**: fuente mayor que la mediana del documento y menos de
  120 caracteres. Nivel relativo (``#``, ``##``, ``###``) según el
  orden descendente de las fuentes candidatas.
- **Lista**: inicia con ``-``, ``•``, ``*`` o patrones ``1.``, ``a)``,
  ``i.`` → se normaliza a ``-``.
- **Párrafo**: todo lo demás; bloques consecutivos se unen (continúan
  el mismo párrafo).
- Los bloques de whitespace puro se descartan.
"""

import re
import statistics
from dataclasses import dataclass
from typing import Literal

from adapters.markdown.page_segmenter import TextBlock

HEADING_MAX_CHARS = 120
MAX_HEADING_LEVEL = 3

_BOM = "﻿"

_LIST_BULLET_RE = re.compile(r"^[-•*]\s+(.+)$", re.DOTALL)
_LIST_ORDERED_RE = re.compile(r"^(?:\d+|[a-z]|[ivxl]+)[.)]\s+(.+)$", re.DOTALL)

BlockKind = Literal["heading", "list", "paragraph"]


@dataclass(frozen=True)
class ClassifiedBlock:
    """Bloque clasificado listo para renderizar a Markdown."""

    kind: BlockKind
    level: int  # 1-3 para encabezados; 0 para el resto
    text: str


def classify_blocks(blocks: list[TextBlock]) -> list[ClassifiedBlock]:
    """Clasifica bloques en encabezados, listas y párrafos."""
    cleaned = _discard_whitespace(blocks)
    if not cleaned:
        return []
    median_size = statistics.median(block.font_size for block in cleaned)
    heading_levels = _heading_levels_by_relative_size(cleaned, median_size)

    classified: list[ClassifiedBlock] = []
    for block in cleaned:
        level = heading_levels.get(block.font_size)
        if level is not None and len(block.text) < HEADING_MAX_CHARS:
            classified.append(
                ClassifiedBlock(kind="heading", level=level, text=block.text)
            )
        elif (match := _LIST_BULLET_RE.match(block.text)) or (
            match := _LIST_ORDERED_RE.match(block.text)
        ):
            classified.append(
                ClassifiedBlock(kind="list", level=0, text=match.group(1))
            )
        else:
            classified.append(
                ClassifiedBlock(kind="paragraph", level=0, text=block.text)
            )
    return _merge_consecutive_paragraphs(classified)


def _discard_whitespace(blocks: list[TextBlock]) -> list[TextBlock]:
    cleaned = [
        TextBlock(
            text=block.text.removeprefix(_BOM), font_size=block.font_size,
            bbox=block.bbox,
        )
        for block in blocks
    ]
    return [block for block in cleaned if block.text.strip()]


def _heading_levels_by_relative_size(
    blocks: list[TextBlock], median_size: float
) -> dict[float, int]:
    """Mapea cada fuente candidata a su nivel relativo de encabezado.

    Solo encabezan candidatos los bloques cortos (< HEADING_MAX_CHARS):
    un texto largo en fuente grande es un párrafo, no un título.
    """
    candidate_sizes = sorted(
        {
            block.font_size
            for block in blocks
            if block.font_size > median_size and len(block.text) < HEADING_MAX_CHARS
        },
        reverse=True,
    )
    return {
        size: min(index + 1, MAX_HEADING_LEVEL)
        for index, size in enumerate(candidate_sizes)
    }


def _merge_consecutive_paragraphs(
    blocks: list[ClassifiedBlock],
) -> list[ClassifiedBlock]:
    """Une párrafos consecutivos: continúan el mismo párrafo."""
    merged: list[ClassifiedBlock] = []
    for block in blocks:
        if (
            block.kind == "paragraph"
            and merged
            and merged[-1].kind == "paragraph"
        ):
            previous = merged.pop()
            merged.append(
                ClassifiedBlock(
                    kind="paragraph",
                    level=0,
                    text=f"{previous.text} {block.text}",
                )
            )
        else:
            merged.append(block)
    return merged
