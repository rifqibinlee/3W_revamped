import os

# Settings() is instantiated at import time (app.core.config), so required
# env vars must exist before any app.* module is imported anywhere in the
# test session. Values are dummies — no test should depend on these pointing
# at a real database; tests that need a real connection set their own paths.
os.environ.setdefault("POSTGRES_DSN", "postgresql+psycopg://test:test@localhost/test")
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core import all_models  # noqa: E402, F401
from app.core.db import Base, get_db  # noqa: E402


@pytest.fixture
def db_session():
    """In-memory SQLite per test — fast, no real Postgres needed for unit
    tests. StaticPool keeps the same connection alive across the session
    (an in-memory SQLite db disappears once its one connection closes)."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
