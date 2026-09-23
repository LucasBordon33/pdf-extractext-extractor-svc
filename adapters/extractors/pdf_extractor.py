"""Adaptador de extracción de texto para documentos PDF.

Implementa el puerto ``TextExtractor`` usando PyPDF2. Toda la
dependencia de la librería queda confinada en este módulo: el dominio
y el resto del sistema solo conocen el contrato abstracto.
"""

from io import BytesIO

from PyPDF2 import PdfReader
from PyPDF2.errors import PdfReadError

from core.exceptions import CorruptFileError, EmptyExtractionError
from domain.ports.text_extractor import TextExtractor


class PdfTextExtractor(TextExtractor):
    """Extrae texto plano de documentos PDF recibidos como bytes."""

    def extract(self, content: bytes, filename: str) -> str:
        reader = self._open_reader(content, filename)
        self._unlock_if_encrypted(reader, filename)
        text = self._read_all_pages(reader)
        self._ensure_text_found(text, filename)
        return text

    def _open_reader(self, content: bytes, filename: str) -> PdfReader:
        try:
            return PdfReader(BytesIO(content))
        except (PdfReadError, ValueError, OSError) as error:
            raise CorruptFileError(
                f"no se pudo leer el PDF '{filename}': {error}"
            ) from error

    def _unlock_if_encrypted(self, reader: PdfReader, filename: str) -> None:
        """Intenta abrir PDFs protegidos sin contraseña de usuario.

        Muchos PDFs restringen permisos (copiar, imprimir) pero son
        legibles con contraseña vacía. Si el cifrado exige credenciales,
        el contenido no puede procesarse.
        """
        if not reader.is_encrypted:
            return
        if reader.decrypt("") == 0:
            raise CorruptFileError(
                f"el PDF '{filename}' esta cifrado y requiere contraseña"
            )

    def _read_all_pages(self, reader: PdfReader) -> str:
        fragments = []
        for page in reader.pages:
            fragments.append(page.extract_text() or "")
        return "".join(fragments)

    def _ensure_text_found(self, text: str, filename: str) -> None:
        if not text.strip():
            raise EmptyExtractionError(
                f"el PDF '{filename}' no contiene texto extraible"
                " (posiblemente escaneado como imagen)"
            )
