from __future__ import annotations  # keeps annotations lazy (see Karya: methods named like builtins)

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Integer, cast, delete, func, select, text
from sqlalchemy.orm import Session

from ..models.monitoring import HealthCheck, Incident, MonitoredService, RestartEvent

if TYPE_CHECKING:
    from ..monitor.monitor import ProbeResult


class MonitorRepository:
    # --- monitor loop (names from the PDF) ------------------------------------------
    def enabled_services(self, s: Session) -> list[MonitoredService]:
        stmt = (
            select(MonitoredService).where(MonitoredService.enabled.is_(True)).order_by(MonitoredService.name)
        )
        return list(s.execute(stmt).scalars())

    def record_check(self, s: Session, service: str, result: ProbeResult) -> None:
        s.add(
            HealthCheck(
                service=service,
                ok=result.ok,
                status_code=result.status_code,
                latency_ms=result.latency_ms,
                error=result.error,
            )
        )

    def open_incident(self, s: Session, service: str) -> Incident | None:
        stmt = select(Incident).where(Incident.service == service, Incident.resolved_at.is_(None))
        return s.execute(stmt.order_by(Incident.id.desc()).limit(1)).scalar_one_or_none()

    def open_or_get_incident(self, s: Session, service: str, error: str) -> Incident:
        incident = self.open_incident(s, service)
        if incident is None:
            incident = Incident(service=service, restarts=0, escalated=False)
            s.add(incident)
        incident.last_error = error[:1000]
        s.flush()
        return incident

    def resolve_incident(self, s: Session, service: str) -> bool:
        incident = self.open_incident(s, service)
        if incident is None:
            return False
        incident.resolved_at = func.now()
        return True

    def restarts_last_hour(self, s: Session, service: str) -> int:
        stmt = select(func.count()).where(
            RestartEvent.service == service,
            RestartEvent.reason.in_(("auto", "failed")),  # manual restarts do not use the automatic budget
            RestartEvent.restarted_at > func.now() - text("interval '1 hour'"),
        )
        return s.execute(stmt).scalar_one()

    def mark_escalated(self, s: Session, incident_id: int) -> None:
        s.get(Incident, incident_id).escalated = True

    def record_restart(self, s: Session, incident_id: int | None, service: str, reason: str = "auto") -> None:
        if incident_id is not None and reason != "failed":
            incident = s.get(Incident, incident_id)
            incident.restarts += 1
        s.add(RestartEvent(service=service, incident_id=incident_id, reason=reason))

    def delete_checks_older_than(self, s: Session, days: int) -> int:
        stmt = delete(HealthCheck).where(
            HealthCheck.checked_at < func.now() - func.make_interval(0, 0, 0, days)
        )
        return s.execute(stmt).rowcount

    # --- service catalog -------------------------------------------------------------
    def get_service(self, s: Session, name: str) -> MonitoredService | None:
        return s.get(MonitoredService, name)

    def all_services(self, s: Session) -> list[MonitoredService]:
        return list(s.execute(select(MonitoredService).order_by(MonitoredService.name)).scalars())

    def add_service(self, s: Session, service: MonitoredService) -> None:
        s.add(service)

    # --- status page -----------------------------------------------------------------
    def latest_checks(self, s: Session) -> dict[str, HealthCheck]:
        stmt = (
            select(HealthCheck)
            .distinct(HealthCheck.service)
            .order_by(HealthCheck.service, HealthCheck.checked_at.desc(), HealthCheck.id.desc())
        )
        return {c.service: c for c in s.execute(stmt).scalars()}

    def recent_checks(self, s: Session, service: str, limit: int) -> list[HealthCheck]:
        stmt = (
            select(HealthCheck)
            .where(HealthCheck.service == service)
            .order_by(HealthCheck.checked_at.desc(), HealthCheck.id.desc())
            .limit(limit)
        )
        return list(s.execute(stmt).scalars())

    def hourly_uptime(self, s: Session, since: datetime) -> list[tuple[str, datetime, float, int]]:
        """(service, hour, share of ok checks, number of checks) for every hour with checks since `since`."""
        hour = func.date_trunc("hour", HealthCheck.checked_at)
        stmt = (
            select(HealthCheck.service, hour, func.avg(cast(HealthCheck.ok, Integer)), func.count())
            .where(HealthCheck.checked_at >= since)
            .group_by(HealthCheck.service, hour)
        )
        return [(service, h, float(uptime), count) for service, h, uptime, count in s.execute(stmt).all()]

    def incidents(self, s: Session, limit: int, open_only: bool = False) -> list[Incident]:
        stmt = select(Incident).order_by(Incident.opened_at.desc(), Incident.id.desc()).limit(limit)
        if open_only:
            stmt = stmt.where(Incident.resolved_at.is_(None))
        return list(s.execute(stmt).scalars())
