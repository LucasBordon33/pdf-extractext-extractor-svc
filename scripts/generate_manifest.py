"""Genera el manifest.json del dataset de stress testing.

Barre tests/stress/pdfs/, calcula para cada PDF su tamaño en bytes, su hash
SHA256 y su número de páginas (vía pypdfium2), y persiste todo en
tests/stress/pdfs/manifest.json.

Uso:
    python scripts/generate_manifest.py
"""

import hashlib
import json
from pathlib import Path

import pypdfium2 as pdfium

PDFS_DIR = Path(__file__).resolve().parent.parent / "tests" / "stress" / "pdfs"
MANIFEST_PATH = PDFS_DIR / "manifest.json"

_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _page_count(path: Path) -> int:
    pdf = pdfium.PdfDocument(str(path))
    try:
        return len(pdf)
    finally:
        pdf.close()


def main() -> None:
    entries = []
    for pdf_path in sorted(PDFS_DIR.glob("*.pdf")):
        entries.append(
            {
                "filename": pdf_path.name,
                "size_bytes": pdf_path.stat().st_size,
                "sha256": _sha256(pdf_path),
                "page_count": _page_count(pdf_path),
            }
        )

    manifest = {"files": entries}
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Manifest generado en {MANIFEST_PATH} ({len(entries)} archivos)")


if __name__ == "__main__":
    main()
