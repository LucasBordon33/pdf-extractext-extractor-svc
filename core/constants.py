"""Constantes compartidas del dominio y la capa de aplicación.

Centraliza valores que aparecen en varios módulos para evitar
duplicación incidental (Duplicate Code) y tener un único punto de
cambio si un umbral o nombre por defecto se ajusta.
"""

BYTES_PER_MB = 1024 * 1024
DEFAULT_FILENAME = "documento.pdf"


def size_limit_message(max_bytes_mb: int, filename: str | None = None) -> str:
    """Mensaje de error de tamaño de archivo excedido.

    Preserva el wording exacto de cada llamador: sin filename usa
    "el archivo excede el maximo de X MB"; con filename usa
    "el archivo '<nombre>' supera el maximo de X MB".
    """
    if filename is None:
        return f"el archivo excede el maximo de {max_bytes_mb} MB"
    return f"el archivo '{filename}' supera el maximo de {max_bytes_mb} MB"
