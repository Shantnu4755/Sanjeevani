from typing import TypeVar

from flask import request
from flask.views import MethodView
from pydantic import BaseModel

from ..exceptions import ValidationError

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class BaseView(MethodView):
    """Parent of every view. Subclasses define only get() and/or post()."""

    init_every_request = False

    @staticmethod
    def parse_body(schema: type[SchemaT]) -> SchemaT:
        data = request.get_json(silent=True)
        if data is None:
            raise ValidationError("Request body must be valid JSON")
        return schema.model_validate(data)

    @staticmethod
    def parse_query(schema: type[SchemaT]) -> SchemaT:
        return schema.model_validate(request.args.to_dict())
