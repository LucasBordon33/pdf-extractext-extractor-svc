"""Fixtures compartidas por toda la suite.

La generación de PDFs vive en ``tests/fixtures/pdf_factory.py``;
aquí solo se expone como fixture de pytest lo que se comparte entre
archivos de test.
"""

import pytest

from tests.fixtures.pdf_factory import pdf_with_text


@pytest.fixture
def pdf_factory():
    """Builder de PDFs válidos con texto visible.

    Variádico: ``pdf_factory("a", "b")`` produce un PDF de dos páginas.
    """
    return pdf_with_text
