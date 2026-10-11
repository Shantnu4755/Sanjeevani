class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str = "Something went wrong", details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class BusinessRuleError(AppError):
    status_code = 400
    code = "business_rule_violation"


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limited"


class ExternalServiceError(AppError):
    status_code = 502
    code = "external_service_error"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"
