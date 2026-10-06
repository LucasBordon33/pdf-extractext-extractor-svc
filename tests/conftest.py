"""Fixtures compartidas por toda la suite.

La generación de PDFs vive en ``tests/fixtures/pdf_factory.py``;
aquí solo se expone como fixture de pytest lo que se comparte entre
archivos de test.

Además se fija el contexto global que hace determinista la suite
independientemente del orden de ejecución: el logging queda
configurado una vez por test (es idempotente) para que ``caplog``
siempre vea la línea JSON del middleware (ISSUE-014).
"""

import pytest

from core.logging import configure_logging
from tests.fixtures.pdf_factory import pdf_with_text


@pytest.fixture
def pdf_factory():
    """Builder de PDFs válidos con texto visible.

    Variádico: ``pdf_factory("a", "b")`` produce un PDF de dos páginas.
    """
    return pdf_with_text


@pytest.fixture(autouse=True)
def _deterministic_logging():
    """Logging conocido por test: la app lo configura al importarse y
    el orden de los módulos no debe cambiar lo que ``caplog`` captura."""
    configure_logging(level="INFO", fmt="json")
