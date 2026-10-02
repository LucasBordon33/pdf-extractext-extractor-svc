"""R11/no-disk (ISSUE-013): ninguna petición escribe en disco.

El endpoint es ``def`` (síncrono), así que el flujo completo, incluida
la atlética lectura streaming del body, se ejercita con un TestClient
síncrono. Se procesa un PDF real de ~9 MB con el CWD y TEMP/TMPDIR
redirigidos a un directorio de solo lectura: si cualquier capa
(starlette, python-multipart, pdfium) hiciera spool, aparecería un
archivo en el snapshot y el test falla.
"""

import os

from fastapi.testclient import TestClient

import main
from tests.fixtures.pdf_factory import pdf_of_size_mb

PDF_CONTENT_TYPE = "application/pdf"


def test_nine_mb_pdf_is_processed_without_disk_writes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setenv("TMP", str(tmp_path))
    try:
        os.chmod(tmp_path, 0o500)
    except OSError:
        pass  # best-effort; la garantía real es el snapshot

    before = {entry.name for entry in tmp_path.iterdir()}
    pdf = pdf_of_size_mb(9)

    with TestClient(main.app) as client:
        response = client.post(
            "/extract", content=pdf, headers={"content-type": PDF_CONTENT_TYPE}
        )

    assert response.status_code == 200
    assert "content" in response.json()
    assert {entry.name for entry in tmp_path.iterdir()} == before