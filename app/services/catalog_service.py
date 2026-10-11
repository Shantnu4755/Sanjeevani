import hmac
import logging

from docker.errors import DockerException

from ..exceptions import ExternalServiceError, NotFoundError, UnauthorizedError
from ..extensions import db
from ..models.monitoring import MonitoredService
from ..monitor.monitor import Restarter
from ..repositories.monitor_repository import MonitorRepository
from ..schemas.status import RestartOut, ServiceCreate

logger = logging.getLogger(__name__)


class CatalogService:
    """Which services Sanjeevani watches (CLI) and manual restarts (API, admin token)."""

    def __init__(self, restarter: Restarter | None = None, admin_token: str = "") -> None:
        self.repo = MonitorRepository()
        self.restarter = restarter
        self.admin_token = admin_token

    def upsert(self, data: ServiceCreate) -> bool:
        """Adds or updates a service; returns True when it was new. Safe to run again."""
        with db.session() as s:
            svc = self.repo.get_service(s, data.name)
            created = svc is None
            if created:
                svc = MonitoredService(name=data.name)
                self.repo.add_service(s, svc)
            svc.container_name = data.container_name
            svc.health_url = data.health_url
            svc.max_restarts_per_hour = data.max_restarts_per_hour
            svc.enabled = data.enabled
        logger.info("service_saved", extra={"service": data.name})
        return created

    def set_enabled(self, name: str, enabled: bool) -> None:
        with db.session() as s:
            svc = self.repo.get_service(s, name)
            if svc is None:
                raise NotFoundError("Service not found", {"service": name})
            svc.enabled = enabled

    def all(self) -> list[MonitoredService]:
        with db.session() as s:
            return self.repo.all_services(s)

    def restart(self, name: str, token: str) -> RestartOut:
        if not self.admin_token or not hmac.compare_digest(token.encode(), self.admin_token.encode()):
            raise UnauthorizedError("A valid X-Admin-Token header is required")
        with db.session() as s:
            svc = self.repo.get_service(s, name)
            if svc is None:
                raise NotFoundError("Service not found", {"service": name})
            container, incident = svc.container_name, self.repo.open_incident(s, name)
        if self.restarter is None:
            raise ExternalServiceError("Restarts are not available in this process")
        try:
            self.restarter.restart(container)
        except DockerException as exc:
            logger.exception("manual_restart_failed", extra={"service": name})
            raise ExternalServiceError(
                "Docker could not restart the container", {"container": container}
            ) from exc
        with db.session() as s:
            self.repo.record_restart(s, incident.id if incident else None, name, reason="manual")
        logger.warning("manual_restart", extra={"service": name})
        return RestartOut(service=name, container_name=container, restarted=True)
