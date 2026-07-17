"""Test configuration.

Force in-memory / no-DB mode before the app package is imported, so the suite is
hermetic and never reaches for a real Postgres.
"""

import os

os.environ["CHECKPOINT_BACKEND"] = "memory"
os.environ["DATABASE_URL"] = ""
os.environ["REDIS_URL"] = ""
os.environ["RATE_LIMIT_PER_MINUTE"] = "0"
os.environ["SLA_SECONDS"] = "0"
os.environ["AUTH_ENABLED"] = "false"
os.environ["JWT_SECRET"] = "test-only-secret-change-me-32bytes"
os.environ["DEMO_USER_PASSWORD"] = "demo-password"
