from unittest.mock import MagicMock

import pytest
from docker.errors import DockerException
from sqlalchemy import func, select

from app import cli
from app.extensions import db
from app.models.monitoring import RestartEvent
from app.monitor.monitor import Alerter, Monitor, Restarter
from app.repositories.monitor_repository import MonitorRepository
from tests.helpers import DOWN, ScriptedProbe, add_check, add_service

ADMIN = {"X-Admin-Token": "test-admin-token"}


def _summary(client) -> dict:
    return client.get("/summary").get_json()["data"]


def test_summary_with_nothing_to_watch(client):
    summary = _summary(client)
    assert (summary["status"], summary["services"], summary["affected"]) == ("unknown", [], [])


def test_summary_degraded_with_bars_sparkline_and_uptime(client):
    add_service("kavach")
    add_service("hisaab")
    for hours_ago in (30, 2, 1):
        add_check("kavach", True, hours_ago=hours_ago, latency=20)
    add_check("kavach", True, latency=40)
    add_check("hisaab", True, hours_ago=3)
    add_check("hisaab", False, hours_ago=0.01)

    summary = _summary(client)
    assert (summary["status"], summary["affected"]) == ("degraded", ["hisaab"])
    kavach = next(s for s in summary["services"] if s["name"] == "kavach")
    assert (kavach["status"], kavach["latency_ms"]) == ("up", 40)
    assert len(kavach["bars"]) == 168 and kavach["bars"][-1]["uptime"] == 1.0
    assert sum(b["checks"] for b in kavach["bars"]) == 4
    assert kavach["sparkline"] == [20, 20, 20, 40]
    assert (kavach["uptime_24h"], kavach["uptime_7d"]) == (1.0, 1.0)
    hisaab = next(s for s in summary["services"] if s["name"] == "hisaab")
    assert (hisaab["status"], hisaab["uptime_24h"]) == ("down", 0.5)


def test_services_without_checks_yet_are_unknown_not_operational(client):
    add_service("kavach")
    add_service("hisaab")
    assert _summary(client)["status"] == "unknown"
    add_check("kavach", True)
    assert _summary(client)["status"] == "operational"


def test_summary_outage_and_operational(client):
    add_service("kavach")
    add_check("kavach", False)
    assert _summary(client)["status"] == "outage"
    add_check("kavach", True)
    assert _summary(client)["status"] == "operational"


def test_incidents_show_on_the_status_page(client):
    add_service("kavach")
    monitor = Monitor(ScriptedProbe(DOWN), MagicMock(spec=Restarter), MagicMock(spec=Alerter), interval=0)
    for _ in range(3):
        monitor._tick()
    summary = _summary(client)
    assert summary["services"][0]["open_incident"]["restarts"] == 1
    [incident] = summary["incidents"]
    assert incident["service"] == "kavach" and incident["duration_seconds"] >= 0
    assert client.get("/incidents?open=true").get_json()["data"][0]["id"] == incident["id"]


def test_services_and_checks_endpoints(client):
    add_service("kavach")
    add_check("kavach", True, latency=15)
    assert client.get("/services").get_json()["data"][0]["status"] == "up"
    checks = client.get("/services/kavach/checks?limit=5").get_json()["data"]
    assert [(c["ok"], c["latency_ms"]) for c in checks] == [(True, 15)]
    assert client.get("/services/nope/checks").status_code == 404
    assert client.get("/services/kavach/checks?limit=0").status_code == 422


def test_manual_restart_needs_the_admin_token(app, client):
    add_service("kavach")
    catalog = app.extensions["sanjeevani"]["catalog"]
    catalog.restarter = MagicMock(spec=Restarter)
    assert client.post("/services/kavach/restart").status_code == 401
    assert client.post("/services/kavach/restart", headers={"X-Admin-Token": "wrong"}).status_code == 401
    resp = client.post("/services/kavach/restart", headers=ADMIN)
    assert resp.status_code == 200 and resp.get_json()["data"]["restarted"] is True
    catalog.restarter.restart.assert_called_once_with("kavach")
    with db.session() as s:
        assert s.execute(select(RestartEvent.reason)).scalar_one() == "manual"
        assert MonitorRepository().restarts_last_hour(s, "kavach") == 0  # manual does not use the budget
    assert client.post("/services/missing/restart", headers=ADMIN).status_code == 404
    catalog.restarter.restart.side_effect = DockerException("refused")
    assert client.post("/services/kavach/restart", headers=ADMIN).status_code == 502
    with db.session() as s:
        assert s.execute(select(func.count()).select_from(RestartEvent)).scalar_one() == 1


def test_get_is_the_only_way_to_read(client):
    assert client.delete("/services/kavach/restart", headers=ADMIN).status_code == 405


@pytest.fixture
def cli_env(app, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", app.config["APP_CONFIG"].database_url)


def test_cli_manages_the_catalog(cli_env, capsys):
    args = ["add-service", "--name", "kavach", "--container", "kavach", "--url", "http://kavach:8000/health"]
    assert cli.main(args) == 0
    assert cli.main([*args, "--max-restarts", "5"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "added kavach -> http://kavach:8000/health",
        "updated kavach -> http://kavach:8000/health",
    ]
    assert cli.main(["disable-service", "--name", "kavach"]) == 0
    assert cli.main(["list-services"]) == 0
    assert "kavach\tdisabled\tcontainer=kavach" in capsys.readouterr().out
    assert cli.main(["enable-service", "--name", "kavach"]) == 0
    assert cli.main(["enable-service", "--name", "ghost"]) == 1
    assert cli.main(["add-service", "--name", "Bad!", "--container", "x", "--url", "ftp://x"]) == 2
