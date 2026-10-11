from flask import Flask

from ..monitor.monitor import Restarter
from ..services.catalog_service import CatalogService
from .health import HealthView
from .status import IncidentListView, ServiceChecksView, ServiceListView, ServiceRestartView, StatusPageView


def register_routes(app: Flask) -> None:
    app.add_url_rule("/health", view_func=HealthView.as_view("health"))
    # project-specific routes are added below this line
    config = app.config["APP_CONFIG"]
    catalog = CatalogService(Restarter(config.docker_url), admin_token=config.admin_token)
    app.extensions["sanjeevani"] = {"catalog": catalog}
    app.add_url_rule("/summary", view_func=StatusPageView.as_view("summary"))
    app.add_url_rule("/services", view_func=ServiceListView.as_view("services"))
    app.add_url_rule("/services/<name>/checks", view_func=ServiceChecksView.as_view("service_checks"))
    app.add_url_rule(
        "/services/<name>/restart", view_func=ServiceRestartView.as_view("service_restart", catalog=catalog)
    )
    app.add_url_rule("/incidents", view_func=IncidentListView.as_view("incidents"))
