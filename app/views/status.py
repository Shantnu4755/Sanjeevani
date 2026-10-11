from flask import request

from ..schemas.status import CheckFilter, IncidentFilter
from ..services.catalog_service import CatalogService
from ..services.status_service import StatusService
from .base import BaseView


class StatusPageView(BaseView):
    """Everything the status page needs, in one call."""

    def __init__(self) -> None:
        self.service = StatusService()

    def get(self):
        return {"data": self.service.summary().model_dump(mode="json")}, 200


class ServiceListView(BaseView):
    def __init__(self) -> None:
        self.service = StatusService()

    def get(self):
        return {"data": [s.model_dump(mode="json") for s in self.service.services()]}, 200


class ServiceChecksView(BaseView):
    def __init__(self) -> None:
        self.service = StatusService()

    def get(self, name: str):
        checks = self.service.checks(name, self.parse_query(CheckFilter))
        return {"data": [c.model_dump(mode="json") for c in checks]}, 200


class IncidentListView(BaseView):
    def __init__(self) -> None:
        self.service = StatusService()

    def get(self):
        incidents = self.service.incidents(self.parse_query(IncidentFilter))
        return {"data": [i.model_dump(mode="json") for i in incidents]}, 200


class ServiceRestartView(BaseView):
    def __init__(self, catalog: CatalogService) -> None:
        self.catalog = catalog

    def post(self, name: str):
        result = self.catalog.restart(name, request.headers.get("X-Admin-Token", ""))
        return {"data": result.model_dump(mode="json")}, 200
