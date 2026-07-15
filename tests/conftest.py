"""Test configuration.

Force in-memory / no-DB mode before the app package is imported, so the suite is
hermetic and never reaches for a real Postgres.
"""

import os

os.environ["CHECKPOINT_BACKEND"] = "memory"
os.environ["DATABASE_URL"] = ""
