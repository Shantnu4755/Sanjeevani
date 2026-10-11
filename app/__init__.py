import uuid

from flask import Flask, g, request

from .config import Config
from .error_handlers import register_error_handlers
from .extensions import db
from .logging_setup import setup_logging
from .views import register_routes


def create_app(config: Config | None = None) -> Flask:
    config = config or Config.from_env()
    setup_logging(config.log_level)

    app = Flask(config.app_name)
    app.config["APP_CONFIG"] = config
    db.init_app(config.database_url)

    @app.before_request
    def assign_request_id() -> None:
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex

    @app.after_request
    def expose_request_id(response):
        response.headers["X-Request-ID"] = g.get("request_id", "")
        return response

    register_error_handlers(app)
    register_routes(app)
    return app
