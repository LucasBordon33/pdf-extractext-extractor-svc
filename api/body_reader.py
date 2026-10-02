"""Lectura del cuerpo HTTP en streaming, sin volcar a disco (R11).

La pauta R11 pide no duplicar buffers y no tocar disco. En lugar de
``await request.body()`` (copia interna de Starlette) o del multipart
de ``python-multipart`` que spool a disco al superar 1 MB, este módulo:

- ``read_body`` acumula el binario crudo en un único ``io.BytesIO``
  leyendo a chunks desde ``request.stream()``.
- ``read_multipart`` parsea el multipart con el parser feedable de
  ``python-multipart`` sobre el mismo stream: el campo ``file`` se
  acumula en memoria y el resto de partes se descarta sin materializar.

Estas son las únicas funciones ``async`` del proyecto: el protocolo
ASGI entrega el body por ``receive`` (await) y no existe forma síncrona
de leerlo sin bloquear el loop o duplicar el buffer completo. El resto
de la capa web, el dominio y el pool son síncronos (ADR-TP-5). Para que
las decisiones de umbral se puedan testear sin asyncio, están extraídas
como helpers puros síncronos (``_ensure_declared_within``,
``_ensure_room``, ``_ensure_not_empty``); el loop ``async`` que queda es
solo pegamento delgado sobre el stream.

Tope duro durante la lectura (no solo por ``Content-Length``): un
cliente que mienta la longitud o use chunked encoding no puede tumba la
réplica. El ``filename`` que devuelve multipart sale sanitizado
(ADR-TP-4), nunca rutas ni bytes de control.
"""

import io
import re

from python_multipart.multipart import MultipartParser, parse_options_header

from core.exceptions import EmptyBodyError, FileTooLargeError, MissingFileFieldError

_BYTES_PER_MB = 1024 * 1024
_MAX_FILENAME_CHARS = 128
_FILE_FIELD_NAME = b"file"
_DEFAULT_FILENAME = "documento.pdf"

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_filename(name: str) -> str:
    """Solo el nombre base: sin rutas, sin bytes de control, acotado.

    ``sanitize_filename("../../etc/passwd")`` → ``"passwd"``. Un nombre
    vacío o inválido cae a un default seguro.
    """
    cleaned = _CONTROL_CHARS.sub("", name)
    basename = cleaned.replace("\\", "/").rsplit("/", 1)[-1]
    return basename[:_MAX_FILENAME_CHARS] or _DEFAULT_FILENAME


async def read_body(request, max_bytes: int) -> bytes:
    """Lee el body crudo en chunks con corte duro en ``max_bytes``.

    Primero responde 413 con el ``Content-Length`` sin tocar el body;
    luego aborta en cuanto la suma de chunks supera el tope. El único
    comportamiento es la frontera ASGI; las decisiones son síncronas.
    """
    _ensure_declared_within(_declared_length(request), max_bytes)

    buffer = io.BytesIO()
    async for chunk in request.stream():
        _ensure_room(buffer.tell(), len(chunk), max_bytes)
        buffer.write(chunk)

    content = buffer.getvalue()
    _ensure_not_empty(content)
    return content


async def read_multipart(request, max_bytes: int) -> tuple[bytes, str]:
    """Extrae el campo ``file`` de un multipart sin spool a disco.

    Devuelve ``(bytes del archivo, filename sanitizado)``. El tope se
    aplica a los bytes del archivo en sí (el sobre multipart puede ser
    más grande sin que eso importe).
    """
    _, params = parse_options_header(request.headers.get("content-type"))
    boundary = params.get(b"boundary")
    if not boundary:
        raise EmptyBodyError("multipart invalido: falta el boundary")

    parser, collector = _build_multipart_parser(max_bytes, boundary)
    async for chunk in request.stream():
        parser.write(chunk)
    parser.finalize()
    return collector.result()


def _declared_length(request) -> int | None:
    """Devuelve el ``Content-Length`` si es un entero válido, si no None."""
    header = request.headers.get("content-length")
    if header is None or not header.isdigit():
        return None
    return int(header)


def _ensure_declared_within(declared: int | None, max_bytes: int) -> None:
    """Rechaza 413 por el header antes de leer, sin bloquear nada."""
    if declared is not None and declared > max_bytes:
        _raise_too_large(max_bytes)


def _ensure_room(current: int, incoming: int, max_bytes: int) -> None:
    """Aborta en cuanto el acumulado más el chunk entrante excede el tope."""
    if current + incoming > max_bytes:
        _raise_too_large(max_bytes)


def _ensure_not_empty(content: bytes) -> None:
    if not content:
        raise EmptyBodyError("el body de la peticion esta vacio")


def _build_multipart_parser(
    max_bytes: int, boundary: bytes
) -> tuple[MultipartParser, "_FileCollector"]:
    """Parser feedable + colector del campo ``file``.

    Fabricado así para que el parseo (síncrono) sea testeable sin
    pasar por el loop async del socket.
    """
    collector = _FileCollector(max_bytes)
    callbacks = {
        "on_part_begin": collector.on_part_begin,
        "on_header_field": collector.on_header_field,
        "on_header_value": collector.on_header_value,
        "on_header_end": collector.on_header_end,
        "on_headers_finished": collector.on_headers_finished,
        "on_part_data": collector.on_part_data,
    }
    return MultipartParser(boundary, callbacks), collector


def _raise_too_large(max_bytes: int) -> None:
    raise FileTooLargeError(
        "el archivo excede el maximo de " f"{max_bytes // _BYTES_PER_MB} MB"
    )


class _FileCollector:
    """Acumula en memoria los bytes del campo ``file`` del multipart.

    Los demás campos se ignoran sin materializarlos. Si el archivo
    supera ``max_bytes`` se aborta apenas se detecta, sin llegar a
    almacenarlo completo.
    """

    def __init__(self, max_bytes: int) -> None:
        self._max_bytes = max_bytes
        self._header_field: bytes = b""
        self._header_value: bytes = b""
        self._headers: list[tuple[bytes, bytes]] = []
        self._in_file_part = False
        self._filename: str | None = None
        self._buffer = io.BytesIO()

    def on_part_begin(self) -> None:
        self._header_field = b""
        self._header_value = b""
        self._headers = []
        self._in_file_part = False
        self._filename = None

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_field += data[start:end]

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._header_value += data[start:end]

    def on_header_end(self) -> None:
        self._headers.append(
            (self._header_field.lower(), self._header_value)
        )
        self._header_field = b""
        self._header_value = b""

    def on_headers_finished(self) -> None:
        disposition, options = parse_options_header(
            dict(self._headers).get(b"content-disposition", b"")
        )
        if disposition == b"form-data" and options.get(b"name") == _FILE_FIELD_NAME:
            filename = options.get(b"filename")
            self._in_file_part = filename is not None
            self._filename = self._decode_filename(filename)

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if not self._in_file_part:
            return
        size = end - start
        if self._buffer.tell() + size > self._max_bytes:
            _raise_too_large(self._max_bytes)
        self._buffer.write(data[start:end])

    def result(self) -> tuple[bytes, str]:
        if not self._in_file_part or self._filename is None:
            raise MissingFileFieldError(
                "el multipart debe incluir un campo 'file' con su filename"
            )
        content = self._buffer.getvalue()
        if not content:
            raise EmptyBodyError("el campo 'file' del multipart esta vacio")
        return content, self._filename

    @staticmethod
    def _decode_filename(raw: bytes | None) -> str | None:
        if raw is None:
            return None
        return sanitize_filename(raw.decode("utf-8", errors="replace"))