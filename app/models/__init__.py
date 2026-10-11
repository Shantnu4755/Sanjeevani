"""Import every model module here so Alembic autogenerate and create_all see all tables."""

from .monitoring import HealthCheck, Incident, MonitoredService, RestartEvent

__all__ = ["HealthCheck", "Incident", "MonitoredService", "RestartEvent"]
