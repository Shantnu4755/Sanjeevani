import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch

import pytest
import requests
from docker.errors import DockerException
from sqlalchemy import func, select, text

from app.extensions import db
from app.models.monitoring import HealthCheck, Incident, RestartEvent
from app.monitor.monitor import Alerter, HealthProbe, Monitor, Restarter
from tests.helpers import DOWN, OK, ScriptedProbe, add_check, add_service


def _monitor(probe, restarter=None, alerter=None) -> Monitor:
    return Monitor(
        probe, restarter or MagicMock(spec=Restarter), alerter or MagicMock(spec=Alerter), interval=0
    )


def _ticks(monitor: Monitor, n: int) -> None:
    for _ in range(n):
        monitor._tick()


def _incidents() -> list[Incident]:
    with db.session() as s:
        return list(s.execute(select(Incident).order_by(Incident.id)).scalars())


# --- PDF "Tests to write" ---------------------------------------------------------------


def test_three_failures_trigger_one_restart(app):
    add_service()
    monitor = _monitor(ScriptedProbe(DOWN))
    _ticks(monitor, 2)
    monitor.restarter.restart.assert_not_called()
    _ticks(monitor, 1)
    monitor.restarter.restart.assert_called_once_with("kavach")
    _ticks(monitor, 2)  # failures were reset by the restart: two more are not enough
    assert monitor.restarter.restart.call_count == 1
    assert (
        "RESTARTED: kavach after 3 failed checks (ConnectTimeout)" in monitor.alerter.send.call_args.args[0]
    )
    [incident] = _incidents()
    assert (incident.restarts, incident.resolved_at, incident.last_error) == (1, None, "ConnectTimeout")


def test_a_fourth_restart_within_an_hour_escalates_instead(app):
    add_service(max_restarts=3)
    monitor = _monitor(ScriptedProbe(DOWN))
    _ticks(monitor, 9)  # restarts after checks 3, 6 and 9
    assert monitor.restarter.restart.call_count == 3
    _ticks(monitor, 3)
    assert monitor.restarter.restart.call_count == 3  # paused
    alerts = [c.args[0] for c in monitor.alerter.send.call_args_list]
    assert alerts[-1] == "NEEDS HUMAN: kavach restarted 3 times in 1h, auto-restart paused"
    _ticks(monitor, 3)
    assert (
        sum(a.startswith("NEEDS HUMAN") for a in [c.args[0] for c in monitor.alerter.send.call_args_list])
        == 1
    )
    [incident] = _incidents()
    assert (incident.escalated, incident.restarts) == (True, 3)


def test_recovery_resolves_the_incident(app):
    add_service()
    monitor = _monitor(ScriptedProbe(DOWN, DOWN, DOWN, OK))
    _ticks(monitor, 4)
    [incident] = _incidents()
    assert incident.resolved_at is not None
    monitor.alerter.send.assert_called_with("RECOVERED: kavach is healthy again")


def test_telegram_being_down_does_not_stop_the_loop(app):
    add_service()
    alerter = Alerter("bot-token", "chat-id")
    monitor = _monitor(ScriptedProbe(DOWN), alerter=alerter)
    with patch(
        "app.monitor.monitor.requests.post", side_effect=requests.ConnectionError("telegram down")
    ) as post:
        _ticks(monitor, 3)
    assert post.called
    monitor.restarter.restart.assert_called_once_with("kavach")
    with db.session() as s:
        assert s.execute(select(func.count()).select_from(RestartEvent)).scalar_one() == 1


def test_docker_errors_are_logged_and_alerted(app, caplog):
    add_service()
    restarter = MagicMock(spec=Restarter)
    restarter.restart.side_effect = DockerException("proxy refused")
    monitor = _monitor(ScriptedProbe(DOWN), restarter=restarter)
    _ticks(monitor, 3)
    monitor.alerter.send.assert_called_with("RESTART FAILED: kavach, check the server")
    assert "restart_failed" in caplog.text
    with db.session() as s:
        assert s.execute(select(RestartEvent.reason)).scalars().all() == ["failed"]
    [incident] = _incidents()
    assert incident.restarts == 0  # nothing was actually restarted


def test_a_broken_docker_api_escalates_instead_of_alerting_every_check(app):
    add_service(max_restarts=2)
    restarter = MagicMock(spec=Restarter)
    restarter.restart.side_effect = DockerException("proxy refused")
    monitor = _monitor(ScriptedProbe(DOWN), restarter=restarter)
    _ticks(monitor, 12)
    alerts = [c.args[0] for c in monitor.alerter.send.call_args_list]
    assert alerts == [
        "RESTART FAILED: kavach, check the server",
        "RESTART FAILED: kavach, check the server",
        "NEEDS HUMAN: kavach restarted 2 times in 1h, auto-restart paused",
    ]
    assert restarter.restart.call_count == 2


# --- loop, housekeeping, building blocks -------------------------------------------------


def test_every_check_is_recorded_and_disabled_services_are_skipped(app):
    add_service("kavach")
    add_service("karya-api")
    from app.services.catalog_service import CatalogService

    CatalogService().set_enabled("karya-api", False)
    _ticks(_monitor(ScriptedProbe(OK)), 2)
    with db.session() as s:
        services = s.execute(select(HealthCheck.service)).scalars().all()
    assert services == ["kavach", "kavach"]


def test_housekeeping_deletes_old_checks_once_a_day(app):
    add_service()
    add_check("kavach", True, hours_ago=8 * 24)
    add_check("kavach", True, hours_ago=1)
    monitor = _monitor(ScriptedProbe(OK))
    monitor._housekeeping()
    add_check("kavach", True, hours_ago=9 * 24)
    monitor._housekeeping()  # already ran today
    with db.session() as s:
        remaining = s.execute(
            text("SELECT count(*) FROM health_checks WHERE checked_at < now() - interval '7 days'")
        )
        assert remaining.scalar_one() == 1


def test_run_loop_survives_a_bad_tick_and_stops(app, tmp_path):
    monitor = _monitor(ScriptedProbe(OK))
    calls = {"n": 0}

    def tick() -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database hiccup")
        monitor._stopping.set()

    with (
        patch.object(monitor, "_tick", side_effect=tick),
        patch("app.monitor.monitor.signal.signal"),
        patch("app.liveness.LIVENESS_FILE", tmp_path / "alive"),
    ):
        monitor.run()
    assert calls["n"] == 2 and (tmp_path / "alive").exists()


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(500 if self.path == "/broken" else 200)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        return None


@pytest.fixture
def http_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_health_probe(http_server):
    probe = HealthProbe(timeout=1)
    ok = probe.check(f"{http_server}/health")
    broken = probe.check(f"{http_server}/broken")
    unreachable = probe.check("http://127.0.0.1:9/health")
    assert (ok.ok, ok.status_code) == (True, 200)
    assert (broken.ok, broken.status_code, broken.reason) == (False, 500, "HTTP 500")
    assert (unreachable.ok, unreachable.error) == (False, "ConnectionError")


def test_alerter_sends_or_only_logs(caplog):
    with patch("app.monitor.monitor.requests.post") as post:
        Alerter("", "").send("not configured")
        post.assert_not_called()
        Alerter("token", "42").send("hello")
    post.assert_called_once_with(
        "https://api.telegram.org/bottoken/sendMessage", json={"chat_id": "42", "text": "hello"}, timeout=5
    )
    assert "alert_not_sent" in caplog.text


def test_restarter_connects_lazily_and_restarts_by_name():
    with patch("app.monitor.monitor.docker.DockerClient") as client_cls:
        restarter = Restarter("tcp://docker-proxy:2375")
        client_cls.assert_not_called()
        restarter.restart("kavach")
        restarter.restart("hisaab")
    client_cls.assert_called_once_with(base_url="tcp://docker-proxy:2375", timeout=30)
    client_cls.return_value.containers.get.return_value.restart.assert_called_with(timeout=20)


def test_monitor_entry_point(monkeypatch):
    from app.monitor import __main__ as entry

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    monkeypatch.setenv("CHECK_INTERVAL", "5")
    with patch.object(entry, "db"), patch.object(entry, "Monitor") as fake_monitor:
        entry.main()
    assert fake_monitor.call_args.kwargs["interval"] == 5.0
    fake_monitor.return_value.run.assert_called_once()
