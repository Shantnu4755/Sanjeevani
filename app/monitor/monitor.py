import logging
import signal
import threading
import time
from dataclasses import dataclass

import docker
import requests
from docker.errors import DockerException

from ..extensions import db
from ..liveness import mark_alive
from ..repositories.monitor_repository import MonitorRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    status_code: int | None
    latency_ms: int
    error: str | None

    @property
    def reason(self) -> str:
        return self.error or f"HTTP {self.status_code}"


class HealthProbe:
    def __init__(self, timeout: float = 3.0) -> None:
        self.http = requests.Session()
        self.timeout = timeout

    def check(self, url: str) -> ProbeResult:
        started = time.perf_counter()
        try:
            resp = self.http.get(url, timeout=self.timeout)
            ms = int((time.perf_counter() - started) * 1000)
            return ProbeResult(resp.status_code == 200, resp.status_code, ms, None)
        except requests.RequestException as exc:
            ms = int((time.perf_counter() - started) * 1000)
            return ProbeResult(False, None, ms, type(exc).__name__)


class Alerter:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self.chat_id = chat_id
        self.configured = bool(bot_token and chat_id)

    def send(self, text: str) -> None:
        if not self.configured:
            logger.warning("alert_not_sent", extra={"code": "telegram_not_configured", "error_message": text})
            return
        try:
            resp = requests.post(self.url, json={"chat_id": self.chat_id, "text": text}, timeout=5)
            resp.raise_for_status()
        except requests.RequestException:
            logger.exception("alert_failed")  # an alert failure must never stop monitoring


class Restarter:
    def __init__(self, docker_url: str) -> None:
        self.docker_url = docker_url
        self._client: docker.DockerClient | None = None  # connect on first use: the proxy may start later

    def restart(self, container_name: str) -> None:
        if self._client is None:
            self._client = docker.DockerClient(base_url=self.docker_url, timeout=30)
        self._client.containers.get(container_name).restart(timeout=20)


class Monitor:
    FAILURES_BEFORE_RESTART = 3
    HOUSEKEEPING_SECONDS = 86_400
    KEEP_CHECKS_DAYS = 7

    def __init__(
        self, probe: HealthProbe, restarter: Restarter, alerter: Alerter, interval: float = 30.0
    ) -> None:
        self.probe, self.restarter, self.alerter = probe, restarter, alerter
        self.interval = interval
        self.repo = MonitorRepository()
        self._failures: dict[str, int] = {}
        self._stopping = threading.Event()
        self._last_housekeeping = float("-inf")

    def run(self) -> None:
        signal.signal(signal.SIGTERM, lambda *_: self._stopping.set())
        signal.signal(signal.SIGINT, lambda *_: self._stopping.set())
        logger.info("monitor_started")
        while not self._stopping.is_set():
            mark_alive()
            try:
                self._tick()
            except Exception:
                logger.exception("monitor_tick_failed")  # one bad tick never kills the loop
            self._stopping.wait(self.interval)
        logger.info("monitor_stopped")

    def _tick(self) -> None:
        with db.session() as s:
            services = self.repo.enabled_services(s)
        for svc in services:
            result = self.probe.check(svc.health_url)
            with db.session() as s:
                self.repo.record_check(s, svc.name, result)
            if result.ok:
                self._on_healthy(svc)
            else:
                self._on_unhealthy(svc, result)
        self._housekeeping()

    def _on_healthy(self, svc) -> None:
        # Always look for an open incident: an automatic restart resets the failure count, and a
        # restarted monitor forgets it, so the count alone would leave incidents open forever.
        self._failures.pop(svc.name, None)
        with db.session() as s:
            resolved = self.repo.resolve_incident(s, svc.name)
        if resolved:
            self.alerter.send(f"RECOVERED: {svc.name} is healthy again")

    def _on_unhealthy(self, svc, result: ProbeResult) -> None:
        count = self._failures.get(svc.name, 0) + 1
        self._failures[svc.name] = count
        if count < self.FAILURES_BEFORE_RESTART:
            return

        with db.session() as s:
            incident = self.repo.open_or_get_incident(s, svc.name, result.reason)
            recent = self.repo.restarts_last_hour(s, svc.name)

        if recent >= svc.max_restarts_per_hour:
            if not incident.escalated:
                with db.session() as s:
                    self.repo.mark_escalated(s, incident.id)
                self.alerter.send(
                    f"NEEDS HUMAN: {svc.name} restarted {recent} times in 1h, auto-restart paused"
                )
            return

        try:
            self.restarter.restart(svc.container_name)
            with db.session() as s:
                self.repo.record_restart(s, incident.id, svc.name)
            self._failures[svc.name] = 0
            self.alerter.send(f"RESTARTED: {svc.name} after {count} failed checks ({result.reason})")
        except DockerException:
            logger.exception("restart_failed", extra={"service": svc.name})
            # A failed attempt uses the same hourly budget and resets the count, so a broken Docker
            # API means one alert per attempt and then escalation, not an alert every check.
            with db.session() as s:
                self.repo.record_restart(s, incident.id, svc.name, reason="failed")
            self._failures[svc.name] = 0
            self.alerter.send(f"RESTART FAILED: {svc.name}, check the server")

    def _housekeeping(self) -> None:
        """Once a day: drop health checks older than 7 days so the table stays a few MB."""
        if time.monotonic() - self._last_housekeeping < self.HOUSEKEEPING_SECONDS:
            return
        self._last_housekeeping = time.monotonic()
        with db.session() as s:
            deleted = self.repo.delete_checks_older_than(s, self.KEEP_CHECKS_DAYS)
        if deleted:
            logger.info("old_checks_deleted", extra={"code": deleted})
