from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.extensions import db
from app.monitor.monitor import ProbeResult
from app.schemas.status import ServiceCreate
from app.services.catalog_service import CatalogService

OK = ProbeResult(True, 200, 12, None)
DOWN = ProbeResult(False, None, 3000, "ConnectTimeout")


def add_service(name: str = "kavach", max_restarts: int = 3) -> None:
    CatalogService().upsert(
        ServiceCreate(
            name=name,
            container_name=name,
            health_url=f"http://{name}:8000/health",
            max_restarts_per_hour=max_restarts,
        )
    )


def add_check(service: str, ok: bool, hours_ago: float = 0, latency: int = 10) -> None:
    at = datetime.now(UTC) - timedelta(hours=hours_ago)
    with db.session() as s:
        s.execute(
            text(
                "INSERT INTO health_checks (service, ok, status_code, latency_ms, error, checked_at) "
                "VALUES (:s, :ok, :code, :ms, :err, :at)"
            ),
            {"s": service, "ok": ok, "code": 200 if ok else 503, "ms": latency, "err": None, "at": at},
        )


class ScriptedProbe:
    """Returns results in order; the last one repeats."""

    def __init__(self, *results: ProbeResult) -> None:
        self.results = list(results)
        self.calls = 0

    def check(self, url: str) -> ProbeResult:
        self.calls += 1
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]
