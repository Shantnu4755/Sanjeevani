import logging

from flask import Flask, g, jsonify
from pydantic import ValidationError as PydanticValidationError
from werkzeug.exceptions import HTTPException

from .exceptions import AppError

logger = logging.getLogger(__name__)


def _body(code: str, message: str, details: dict | None = None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": g.get("request_id"),
        }
    }


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(AppError)
    def handle_app_error(err: AppError):
        logger.warning("app_error", extra={"code": err.code, "error_message": err.message})
        return jsonify(_body(err.code, err.message, err.details)), err.status_code

    @app.errorhandler(PydanticValidationError)
    def handle_validation_error(err: PydanticValidationError):
        errors = err.errors(include_url=False, include_context=False)
        return jsonify(_body("validation_error", "Invalid request", {"errors": errors})), 422

    @app.errorhandler(HTTPException)
    def handle_http_error(err: HTTPException):
        code = (err.name or "http_error").lower().replace(" ", "_")
        return jsonify(_body(code, err.description or "")), err.code

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        logger.exception("unhandled_error")
        return jsonify(_body("internal_error", "Something went wrong")), 500
