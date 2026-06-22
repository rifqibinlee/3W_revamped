"""Imported once so Base.metadata knows about every table — needed by
Alembic autogenerate and by the test suite's create_all(), since
SQLAlchemy only registers a model class with the shared Base when its
module has actually been imported somewhere."""

from app.annotations import models as _annotations_models  # noqa: F401
from app.auth import models as _auth_models  # noqa: F401
from app.chat import models as _chat_models  # noqa: F401
from app.pricing import models as _pricing_models  # noqa: F401
from app.rag import models as _rag_models  # noqa: F401
from app.reviews import models as _reviews_models  # noqa: F401
