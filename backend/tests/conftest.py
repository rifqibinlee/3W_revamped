import os

# Settings() is instantiated at import time (app.core.config), so required
# env vars must exist before any app.* module is imported anywhere in the
# test session. Values are dummies — no test should depend on these pointing
# at a real database; tests that need a real connection set their own paths.
os.environ.setdefault("POSTGRES_DSN", "postgresql://test:test@localhost/test")
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "test")
os.environ.setdefault("JWT_SECRET", "test-secret")
