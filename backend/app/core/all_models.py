"""Imported once so Base.metadata knows about every table — needed by
Alembic autogenerate and by the test suite's create_all(), since
SQLAlchemy only registers a model class with the shared Base when its
module has actually been imported somewhere."""

from app.auth import models as _auth_models  # noqa: F401
