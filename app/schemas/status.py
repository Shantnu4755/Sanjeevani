from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field


class ServiceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    container_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    health_url: str = Field(pattern=r"^https?://\S+$", max_length=255)
    max_restarts_per_hour: int = Field(default=3, ge=0, le=20)
    enabled: bool = True


class CheckFilter(BaseModel):
    limit: int = Field(default=100, ge=1, le=500)


class IncidentFilter(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    open: bool = False


class CheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    ok: bool
    status_code: int | None
    latency_ms: int
    error: str | None
    checked_at: datetime


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    service: str
    opened_at: datetime
    resolved_at: datetime | None
    restarts: int
    last_error: str | None
    escalated: bool

    @computed_field
    @property
    def duration_seconds(self) -> int:
        end = self.resolved_at or datetime.now(UTC)
        return max(0, int((end - self.opened_at).total_seconds()))


class ServiceOut(BaseModel):
    name: str
    container_name: str
    health_url: str
    enabled: bool
    max_restarts_per_hour: int
    status: Literal["up", "down", "unknown"]
    latency_ms: int | None
    last_checked_at: datetime | None


class HourBar(BaseModel):
    hour: datetime
    uptime: float | None  # share of passing checks in that hour; None when nothing was checked
    checks: int


class ServiceStatus(ServiceOut):
    uptime_24h: float | None
    uptime_7d: float | None
    bars: list[HourBar]  # 168 hours, oldest first
    sparkline: list[int]  # latency of the last 30 checks, oldest first
    open_incident: IncidentOut | None


class SummaryOut(BaseModel):
    status: Literal["operational", "degraded", "outage", "unknown"]
    affected: list[str]
    services: list[ServiceStatus]
    incidents: list[IncidentOut]
    generated_at: datetime


class RestartOut(BaseModel):
    service: str
    container_name: str
    restarted: bool
