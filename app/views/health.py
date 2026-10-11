from sqlalchemy import text

from ..exceptions import ExternalServiceError
from ..extensions import db
from .base import BaseView


class HealthView(BaseView):
    def get(self):
        try:
            with db.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as exc:
            raise ExternalServiceError("Database unreachable") from exc
        return {"status": "ok"}, 200
