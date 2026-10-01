"""Fabrica de PDFs de prueba, todo en memoria (sin I/O de disco).

Funciones puras y reutilizables: cualquier test que necesite un PDF
lo genera aqui con la variante exacta que necesita. Las contraseñas
de los PDFs cifrados son de prueba, jamas secretos reales.
"""

from io import BytesIO

from PyPDF2 import PdfWriter


def pdf_with_text(*page_texts: str) -> bytes:
    """PDF mínimo y valido con una página visible por cada texto dado.

    Limitación: los textos no deben contener ``( ) \\`` (metacaracteres
    del operador Tj del formato PDF).
    """
    page_count = len(page_texts)
    font_id = 3
    page_ids = [4 + 2 * index for index in range(page_count)]
    content_ids = [5 + 2 * index for index in range(page_count)]

    kids = b" ".join(f"{page_id} 0 R".encode() for page_id in page_ids)
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [" + kids + b"] /Count "
        + str(page_count).encode() + b" >>",
        font_id: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for page_id, content_id, text in zip(
        page_ids, content_ids, page_texts, strict=True
    ):
        stream = f"BT /F1 12 Tf 10 40 Td ({text}) Tj ET".encode()
        objects[page_id] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] "
            b"/Resources << /Font << /F1 " + str(font_id).encode()
            + b" 0 R >> >> /Contents " + str(content_id).encode() + b" 0 R >>"
        )
        objects[content_id] = (
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
            + stream + b"\nendstream"
        )
    return _serialize(objects)


def blank_pdf() -> bytes:
    """Página en blanco: simula un PDF escaneado sin capa de texto."""
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    return _render(writer)


def pdf_with_layout(*lines: tuple[str, float, float]) -> bytes:
    """PDF de una página con líneas (texto, tamaño de fuente, y_offset).

    Para tests del pipeline de Markdown: permite encabezados con
    fuente grande, párrafos y ítems de lista en la misma página.
    """
    parts = [
        f"BT /F1 {size} Tf 10 {y} Td ({text}) Tj ET"
        for text, size, y in lines
    ]
    stream = "\n".join(parts).encode()
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        4: b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
        + stream + b"\nendstream",
        5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    return _serialize(objects)


def encrypted_pdf(user_password: str = "", owner_password: str = "owner") -> bytes:
    """PDF en blanco con cifrado; contraseña de usuario configurable."""
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt(user_password=user_password, owner_password=owner_password)
    return _render(writer)


def _render(writer: PdfWriter) -> bytes:
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _serialize(objects: dict[int, bytes]) -> bytes:
    """Escribe los objetos con su tabla xref y el trailer correctos."""
    buffer = BytesIO()
    buffer.write(b"%PDF-1.4\n")
    offsets = {}
    for object_id in sorted(objects):
        offsets[object_id] = buffer.tell()
        buffer.write(
            f"{object_id} 0 obj\n".encode() + objects[object_id] + b"\nendobj\n"
        )
    xref_position = buffer.tell()
    total = len(objects) + 1
    buffer.write(f"xref\n0 {total}\n".encode())
    buffer.write(b"0000000000 65535 f \n")
    for object_id in sorted(objects):
        buffer.write(f"{offsets[object_id]:010d} 00000 n \n".encode())
    buffer.write(
        f"trailer\n<< /Size {total} /Root 1 0 R >>\n"
        f"startxref\n{xref_position}\n%%EOF".encode()
    )
    return buffer.getvalue()
