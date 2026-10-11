"""Tests for the shared template: health, request ids, error format, config, logging."""

import json
import logging
from unittest.mock import patch

import pytest

from app.config import Config, ConfigError
from app.logging_setup import JsonFormatter


def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_request_id_is_generated_and_echoed(client):
    generated = client.get("/health").headers["X-Request-ID"]
    assert len(generated) == 32
    echoed = client.get("/health", headers={"X-Request-ID": "abc-123"}).headers["X-Request-ID"]
    assert echoed == "abc-123"


def test_unknown_route_returns_json_404(client):
    resp = client.get("/does-not-exist", headers={"X-Request-ID": "req-404"})
    assert resp.status_code == 404
    error = resp.get_json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"] == "req-404"


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_methods_other_than_get_and_post_return_json_405(client, method):
    resp = getattr(client, method)("/health")
    assert resp.status_code == 405
    assert resp.get_json()["error"]["code"] == "method_not_allowed"


def test_health_reports_database_down_as_502(client):
    with patch("app.views.health.db") as fake_db:
        fake_db.engine.connect.side_effect = OSError("connection refused")
        resp = client.get("/health")
    assert resp.status_code == 502
    assert resp.get_json()["error"]["code"] == "external_service_error"


def test_unexpected_error_returns_generic_500(client):
    with patch("app.views.health.HealthView.get", side_effect=RuntimeError("secret detail")):
        resp = client.get("/health")
    assert resp.status_code == 500
    assert resp.get_json()["error"]["code"] == "internal_error"
    assert "secret detail" not in resp.get_data(as_text=True)


def test_config_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ConfigError):
        Config.from_env()


def test_config_reads_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h/db")
    monkeypatch.setenv("APP_NAME", "sanjeevani")
    monkeypatch.setenv("DEBUG", "TRUE")
    config = Config.from_env()
    assert (config.app_name, config.debug, config.log_level) == ("sanjeevani", True, "INFO")


def test_json_formatter_includes_request_id_and_extra_fields(app):
    record = logging.LogRecord("t", logging.ERROR, __file__, 1, "boom", None, None)
    record.code = "conflict"
    with app.test_request_context("/"):
        from flask import g

        g.request_id = "rid-1"
        payload = json.loads(JsonFormatter().format(record))
    assert payload["request_id"] == "rid-1"
    assert payload["code"] == "conflict"
    assert payload["message"] == "boom"
