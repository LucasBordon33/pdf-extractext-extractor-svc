"""Tests de configuración Twelve-Factor (factores II y III).

Toda la configuración proviene de variables de entorno con defaults
razonables: ``docker compose up --build`` debe funcionar sin ``.env``.
"""

import pytest
from pydantic import ValidationError

from core.config import Settings


class TestDefaults:
    def test_provides_reasonable_defaults(self):
        settings = Settings()
        assert settings.max_upload_size_mb == 12
        assert settings.extract_timeout_seconds == 25.0
        assert settings.allowed_mime_types == ["application/pdf"]
        assert settings.env == "development"
        assert settings.log_level == "INFO"
        assert settings.log_format == "json"

    def test_provides_network_defaults(self):
        settings = Settings()
        assert settings.port == 8000
        assert settings.host == "0.0.0.0"
        assert settings.uvicorn_workers == 2

    def test_provides_concurrency_defaults(self):
        settings = Settings()
        assert settings.extraction_pool_size == 2
        assert settings.max_concurrent_extractions == 4
        assert settings.queue_max_size == 64
        assert settings.admission_timeout_seconds == 10.0

    def test_does_not_require_any_env_variable(self):
        Settings()  # no debe lanzar


class TestLoadingFromEnvironment:
    def test_reads_scalar_values(self, monkeypatch):
        monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "25")
        monkeypatch.setenv("EXTRACT_TIMEOUT_SECONDS", "60")
        monkeypatch.setenv("ENV", "production")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        settings = Settings()

        assert settings.max_upload_size_mb == 25
        assert settings.extract_timeout_seconds == 60.0
        assert settings.env == "production"
        assert settings.log_level == "DEBUG"

    def test_reads_port_binding_from_environment(self, monkeypatch):
        monkeypatch.setenv("PORT", "9000")
        monkeypatch.setenv("HOST", "127.0.0.1")

        settings = Settings()

        assert settings.port == 9000
        assert settings.host == "127.0.0.1"

    def test_reads_concurrency_knobs(self, monkeypatch):
        monkeypatch.setenv("UVICORN_WORKERS", "4")
        monkeypatch.setenv("EXTRACTION_POOL_SIZE", "3")
        monkeypatch.setenv("MAX_CONCURRENT_EXTRACTIONS", "8")
        monkeypatch.setenv("QUEUE_MAX_SIZE", "128")
        monkeypatch.setenv("ADMISSION_TIMEOUT_SECONDS", "5.5")

        settings = Settings()

        assert settings.uvicorn_workers == 4
        assert settings.extraction_pool_size == 3
        assert settings.max_concurrent_extractions == 8
        assert settings.queue_max_size == 128
        assert settings.admission_timeout_seconds == 5.5

    def test_reads_log_format_from_environment(self, monkeypatch):
        monkeypatch.setenv("LOG_FORMAT", "text")
        assert Settings().log_format == "text"

    def test_reads_mime_types_as_comma_separated_list(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_MIME_TYPES", "application/pdf, image/pdf")

        settings = Settings()

        assert settings.allowed_mime_types == ["application/pdf", "image/pdf"]

    def test_env_names_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("max_upload_size_mb", "5")
        assert Settings().max_upload_size_mb == 5


class TestValidation:
    def test_rejects_non_positive_upload_size(self, monkeypatch):
        monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "0")
        with pytest.raises(ValidationError):
            Settings()

    def test_rejects_non_positive_timeout(self, monkeypatch):
        monkeypatch.setenv("EXTRACT_TIMEOUT_SECONDS", "-1")
        with pytest.raises(ValidationError):
            Settings()

    @pytest.mark.parametrize("bad_port", ["0", "65536", "-1"])
    def test_rejects_port_out_of_range(self, monkeypatch, bad_port):
        monkeypatch.setenv("PORT", bad_port)
        with pytest.raises(ValidationError):
            Settings()

    def test_rejects_empty_host(self, monkeypatch):
        monkeypatch.setenv("HOST", "")
        with pytest.raises(ValidationError):
            Settings()

    @pytest.mark.parametrize(
        ("variable", "value"),
        [
            ("UVICORN_WORKERS", "0"),
            ("EXTRACTION_POOL_SIZE", "0"),
            ("MAX_CONCURRENT_EXTRACTIONS", "0"),
            ("QUEUE_MAX_SIZE", "0"),
            ("ADMISSION_TIMEOUT_SECONDS", "0"),
        ],
    )
    def test_rejects_non_positive_concurrency_knobs(
        self, monkeypatch, variable, value
    ):
        monkeypatch.setenv(variable, value)
        with pytest.raises(ValidationError):
            Settings()

    def test_rejects_unknown_log_format(self, monkeypatch):
        monkeypatch.setenv("LOG_FORMAT", "xml")
        with pytest.raises(ValidationError):
            Settings()

    def test_rejects_empty_mime_type_list(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_MIME_TYPES", "")
        with pytest.raises(ValidationError):
            Settings()

    def test_rejects_mime_list_with_blank_entries(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_MIME_TYPES", "application/pdf, ,image/pdf")
        with pytest.raises(ValidationError):
            Settings()

    def test_rejects_unknown_log_level(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "CHATTY")
        with pytest.raises(ValidationError):
            Settings()

    def test_rejects_unknown_env(self, monkeypatch):
        monkeypatch.setenv("ENV", "localhost")
        with pytest.raises(ValidationError):
            Settings()

    def test_rejects_non_numeric_size(self, monkeypatch):
        monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "diez")
        with pytest.raises(ValidationError):
            Settings()


class TestDerivedBehavior:
    def test_is_production_helper(self, monkeypatch):
        monkeypatch.setenv("ENV", "production")
        assert Settings().is_production is True

    def test_is_production_false_in_development(self):
        assert Settings().is_production is False
