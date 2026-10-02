"""Construcción de bodies HTTP para tests (ISSUE-012).

``httpx`` solo emite multipart cuando hay ``files=``; para probar el
caso "multipart sin el campo ``file``" hace falta armar el body a mano.
"""


def multipart_without_file(name: str = "nota", value: str = "hola") -> tuple[bytes, str]:
    """Body multipart/form-data válido pero sin campo ``file``.

    Devuelve ``(body, content_type)`` listos para ``client.post(content=...)``.
    """
    boundary = "----testboundary012"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{name}"\r\n'
        "\r\n"
        f"{value}\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    return body, f"multipart/form-data; boundary={boundary}"


def multipart_without_file_kwargs() -> dict:
    """Kwargs de POST para el caso multipart sin archivo."""
    content, content_type = multipart_without_file()
    return {"content": content, "headers": {"content-type": content_type}}