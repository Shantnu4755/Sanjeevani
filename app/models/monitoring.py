from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ..extensions import Base


class MonitoredService(Base):
    __tablename__ = "monitored_services"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    container_name: Mapped[str] = mapped_column(String(128))
    health_url: Mapped[str] = mapped_column(String(255))
    max_restarts_per_hour: Mapped[int] = mapped_column(Integer, default=3)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class HealthCheck(Base):
    __tablename__ = "health_checks"
    __table_args__ = (Index("ix_health_checks_service_checked_at", "service", "checked_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    service: Mapped[str] = mapped_column(String(64))
    ok: Mapped[bool] = mapped_column(Boolean)
    status_code: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (Index("ix_incidents_service_resolved_at", "service", "resolved_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    service: Mapped[str] = mapped_column(String(64))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restarts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)


class RestartEvent(Base):
    """One row per restart: the hourly restart budget needs timestamps, not just a count."""

    __tablename__ = "restart_events"
    __table_args__ = (Index("ix_restart_events_service_restarted_at", "service", "restarted_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    service: Mapped[str] = mapped_column(String(64))
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id", ondelete="SET NULL"))
    reason: Mapped[str] = mapped_column(String(16))  # auto | manual | failed (an attempt Docker refused)
    restarted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
