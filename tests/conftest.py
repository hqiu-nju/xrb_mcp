import os
from pathlib import Path

import pymupdf
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from xrb_mcp.database.connection import get_engine
from xrb_mcp.server.config import get_settings


@pytest.fixture
def pdf_factory(tmp_path):
    def create(name="paper.pdf", pages=None):
        path = tmp_path / name
        doc = pymupdf.open()
        for lines in pages or [
            ["1 Introduction", "SYNTHETIC TEST DOCUMENT. Not scientific evidence."],
            [
                "2 Results",
                "MAXI J1820+070 showed radio ejecta in these fictional MeerKAT observations.",
            ],
        ]:
            page = doc.new_page()
            for index, line in enumerate(lines):
                page.insert_text((72, 72 + index * 35), line, fontsize=10)
        doc.save(path)
        doc.close()
        return path

    return create


class FakeEmbeddings:
    """Deterministic test double; never exposed as a production embedding backend."""

    model = "test-only"
    version = "1"
    dimension = 3

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return [[1.0, float("radio" in t.lower()), float("ejecta" in t.lower())] for t in texts]


@pytest.fixture
def backend():
    return FakeEmbeddings()


@pytest.fixture(scope="session")
def db_engine():
    url = os.environ.get("XRB_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set XRB_TEST_DATABASE_URL to run PostgreSQL integration tests")
    from sqlalchemy.engine import make_url

    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("Integration database name must end in _test (disposable database only)")
    old_url = os.environ.get("XRB_DATABASE_URL")
    os.environ["XRB_DATABASE_URL"] = url
    get_settings.cache_clear()
    get_engine.cache_clear()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(url)
    yield engine
    engine.dispose()
    get_engine().dispose()
    get_engine.cache_clear()
    if old_url is None:
        os.environ.pop("XRB_DATABASE_URL", None)
    else:
        os.environ["XRB_DATABASE_URL"] = old_url
    get_settings.cache_clear()


@pytest.fixture
def session(db_engine):
    with db_engine.connect() as connection:
        transaction = connection.begin()
        session = Session(connection, join_transaction_mode="create_savepoint")
        yield session
        session.close()
        transaction.rollback()


@pytest.fixture
def empty_committed_database(db_engine):
    """For subprocess MCP tests; destructive operations are confined to the *_test DB."""

    def clear():
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE sources, papers, collections CASCADE"))

    clear()
    yield db_engine
    clear()
