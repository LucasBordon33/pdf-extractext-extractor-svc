"""Valida la integridad del dataset de stress testing.

Lee tests/stress/pdfs/manifest.json y verifica que cada PDF en disco coincide
en tamaño en bytes y hash SHA256 con lo registrado. Sale con código 1 si algo
falla (archivo faltante, tamaño o hash distinto).

Uso:
    python tests/stress/verify_dataset.py
"""

import hashlib
import json
import sys
from pathlib import Path

PDFS_DIR = Path(__file__).resolve().parent / "pdfs"
MANIFEST_PATH = PDFS_DIR / "manifest.json"

_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    assert MANIFEST_PATH.is_file(), (
        f"No existe el manifest: {MANIFEST_PATH}. Ejecuta scripts/generate_manifest.py"
    )

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = manifest["files"]

    failures = 0
    for entry in entries:
        path = PDFS_DIR / entry["filename"]

        if not path.is_file():
            print(f"FALLO: {entry['filename']} no existe en disco")
            failures += 1
            continue

        size = path.stat().st_size
        assert size == entry["size_bytes"], (
            f"{entry['filename']}: tamaño esperado {entry['size_bytes']}, actual {size}"
        )

        digest = _sha256(path)
        assert digest == entry["sha256"], (
            f"{entry['filename']}: hash esperado {entry['sha256']}, actual {digest}"
        )

        print(f"OK: {entry['filename']} ({size} bytes)")

    if failures:
        print(f"{failures} archivo(s) faltantes")
        return 1

    print(f"Dataset válido: {len(entries)} archivos verificados")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"FALLO: {exc}")
        sys.exit(1)
