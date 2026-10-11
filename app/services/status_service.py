from datetime import UTC, datetime, timedelta

from ..exceptions import NotFoundError
from ..extensions import db
from ..models.monitoring import HealthCheck, MonitoredService
from ..repositories.monitor_repository import MonitorRepository
from ..schemas.status import (
    CheckFilter,
    CheckOut,
    HourBar,
    IncidentFilter,
    IncidentOut,
    ServiceOut,
    ServiceStatus,
    SummaryOut,
)

HOURS = 168  # the status page shows 7 days, one bar per hour
SPARKLINE_POINTS = 30


class StatusService:
    def __init__(self) -> None:
        self.repo = MonitorRepository()

    def summary(self) -> SummaryOut:
        now = datetime.now(UTC)
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        hours = [current_hour - timedelta(hours=HOURS - 1 - i) for i in range(HOURS)]
        with db.session() as s:
            services = [svc for svc in self.repo.all_services(s) if svc.enabled]
            latest = self.repo.latest_checks(s)
            hourly = {
                (service, hour.astimezone(UTC)): (uptime, count)
                for service, hour, uptime, count in self.repo.hourly_uptime(s, hours[0])
            }
            open_incidents = {i.service: i for i in self.repo.incidents(s, 100, open_only=True)}
            recent_incidents = [IncidentOut.model_validate(i) for i in self.repo.incidents(s, 20)]
            sparklines = {
                svc.name: [
                    c.latency_ms for c in reversed(self.repo.recent_checks(s, svc.name, SPARKLINE_POINTS))
                ]
                for svc in services
            }

        statuses = []
        for svc in services:
            bars = [
                HourBar(
                    hour=h,
                    uptime=hourly.get((svc.name, h), (None, 0))[0],
                    checks=hourly.get((svc.name, h), (None, 0))[1],
                )
                for h in hours
            ]
            incident = open_incidents.get(svc.name)
            statuses.append(
                ServiceStatus(
                    **_service_out(svc, latest.get(svc.name)).model_dump(),
                    uptime_24h=_weighted(bars[-24:]),
                    uptime_7d=_weighted(bars),
                    bars=bars,
                    sparkline=sparklines[svc.name],
                    open_incident=IncidentOut.model_validate(incident) if incident else None,
                )
            )

        affected = [s.name for s in statuses if s.status == "down"]
        checked = [
            s for s in statuses if s.status != "unknown"
        ]  # a service with no checks yet proves nothing
        if not checked:
            overall = "unknown"
        elif len(affected) == len(checked):
            overall = "outage"
        else:
            overall = "degraded" if affected else "operational"
        return SummaryOut(
            status=overall, affected=affected, services=statuses, incidents=recent_incidents, generated_at=now
        )

    def services(self) -> list[ServiceOut]:
        with db.session() as s:
            latest = self.repo.latest_checks(s)
            return [_service_out(svc, latest.get(svc.name)) for svc in self.repo.all_services(s)]

    def checks(self, name: str, f: CheckFilter) -> list[CheckOut]:
        with db.session() as s:
            if self.repo.get_service(s, name) is None:
                raise NotFoundError("Service not found", {"service": name})
            return [CheckOut.model_validate(c) for c in self.repo.recent_checks(s, name, f.limit)]

    def incidents(self, f: IncidentFilter) -> list[IncidentOut]:
        with db.session() as s:
            return [IncidentOut.model_validate(i) for i in self.repo.incidents(s, f.limit, open_only=f.open)]


def _service_out(svc: MonitoredService, last: HealthCheck | None) -> ServiceOut:
    return ServiceOut(
        name=svc.name,
        container_name=svc.container_name,
        health_url=svc.health_url,
        enabled=svc.enabled,
        max_restarts_per_hour=svc.max_restarts_per_hour,
        status="unknown" if last is None else ("up" if last.ok else "down"),
        latency_ms=last.latency_ms if last else None,
        last_checked_at=last.checked_at if last else None,
    )


def _weighted(bars: list[HourBar]) -> float | None:
    checks = sum(b.checks for b in bars)
    if not checks:
        return None
    return round(sum((b.uptime or 0.0) * b.checks for b in bars) / checks, 4)
