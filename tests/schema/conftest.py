import pytest

from plumb.store.ddl import open_run_db


@pytest.fixture
def db():
    conn = open_run_db(":memory:")
    yield conn
    conn.close()
