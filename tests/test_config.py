import pytest
from pydantic import ValidationError

from core.config import Settings


class TestDefaults:
    def test_provides_reasonable_defaults(self):
        settings = Settings()
        assert settings.max_upload_size_mb == 10
        assert settings.extract_timeout_seconds == 30
        assert settings.allowed_mime_types == ["application/pdf"]
        assert settings.env == "development"
        assert settings.log_level == "INFO"

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
        assert settings.extract_timeout_seconds == 60
        assert settings.env == "production"
        assert settings.log_level == "DEBUG"

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
