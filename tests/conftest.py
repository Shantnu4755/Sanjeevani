import os

import pytest

from app import create_app
from app.config import Config
from app.extensions import Base, db


@pytest.fixture(scope="session")
def app():
    config = Config(
        app_name="test",
        database_url=os.environ["TEST_DATABASE_URL"],
        log_level="WARNING",
        debug=False,
        docker_url="tcp://127.0.0.1:9",
        admin_token="test-admin-token",
    )
    application = create_app(config)
    Base.metadata.drop_all(db.engine)
    Base.metadata.create_all(db.engine)
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def clean_tables(app):
    yield
    with db.engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
