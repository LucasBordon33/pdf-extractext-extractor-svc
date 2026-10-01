"""Ensamblador de Markdown: bloques clasificados → documento final.

Decisiones documentadas (ADR-TP-2):

- **Separador de página** (``\\n\\n---\\n\\n``): el TP requiere marcar
  el límite físico de páginas para trazabilidad del informe; las
  páginas vacías no emiten separador.
- Los encabezados se renderizan con ``#`` según nivel; los párrafos
  se unen con ``\\n\\n`` **sin romper líneas internas**.
- Limpieza final: ``\\r\\n → \\n``, colapsar 3+ saltos a 2, quitar
  espacios finales y decodificar entidades HTML comunes.
"""

import html
import re

from adapters.markdown.block_classifier import ClassifiedBlock

PAGE_SEPARATOR = "\n\n---\n\n"

_EXCESS_NEWLINES_RE = re.compile(r"\n{3,}")


def build_page_markdown(blocks: list[ClassifiedBlock]) -> str:
    """Ensambla el Markdown de una página."""
    parts = []
    for block in blocks:
        if block.kind == "heading":
            parts.append(f"{'#' * block.level} {block.text}")
        elif block.kind == "list":
            parts.append(f"- {block.text}")
        else:
            parts.append(block.text)
    return _finalize("\n\n".join(parts))


def build_document(page_markdowns: list[str]) -> str:
    """Une el Markdown de las páginas con el separador de página."""
    pages = [page for page in page_markdowns if page.strip()]
    return _finalize(PAGE_SEPARATOR.join(pages))


def _finalize(text: str) -> str:
    """Limpieza final determinista del documento."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = _EXCESS_NEWLINES_RE.sub("\n\n", text)
    text = html.unescape(text)
    return text.strip()
