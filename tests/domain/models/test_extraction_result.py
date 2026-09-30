"""Tests del modelo de dominio ExtractionResult."""

from dataclasses import FrozenInstanceError

import pytest

from domain.models.extraction_result import ExtractionResult


def sample_result(**overrides) -> ExtractionResult:
    defaults = {
        "markdown": "# Titulo\n\ncontenido",
        "page_count": 3,
        "pages_processed": 2,
        "duration_ms": 12.5,
    }
    return ExtractionResult(**{**defaults, **overrides})


class TestExtractionResult:
    def test_exposes_all_fields(self):
        result = sample_result()
        assert result.markdown == "# Titulo\n\ncontenido"
        assert result.page_count == 3
        assert result.pages_processed == 2
        assert result.duration_ms == 12.5

    def test_is_frozen(self):
        result = sample_result()
        with pytest.raises(FrozenInstanceError):
            result.page_count = 99

    def test_equality_by_value(self):
        assert sample_result() == sample_result()

    def test_rejects_pages_processed_greater_than_page_count(self):
        with pytest.raises(ValueError, match="pages_processed"):
            sample_result(page_count=2, pages_processed=3)

    def test_rejects_negative_page_count(self):
        with pytest.raises(ValueError, match="page_count"):
            sample_result(page_count=-1)

    def test_rejects_negative_duration(self):
        with pytest.raises(ValueError, match="duration_ms"):
            sample_result(duration_ms=-0.1)
