from app.config import Settings


def test_url_derivation_from_plain_postgres_url():
    s = Settings(database_url="postgresql://u:p@h:5432/db", checkpoint_backend="auto")
    assert s.sqlalchemy_async_url == "postgresql+psycopg://u:p@h:5432/db"
    assert s.sqlalchemy_sync_url == "postgresql+psycopg://u:p@h:5432/db"
    assert s.psycopg_conninfo == "postgresql://u:p@h:5432/db"
    assert s.resolved_checkpoint_backend == "postgres"


def test_url_derivation_is_idempotent_for_driver_url():
    s = Settings(database_url="postgresql+psycopg://u:p@h/db")
    assert s.sqlalchemy_async_url == "postgresql+psycopg://u:p@h/db"
    assert s.psycopg_conninfo == "postgresql://u:p@h/db"


def test_auto_backend_is_memory_without_db():
    s = Settings(database_url="", checkpoint_backend="auto")
    assert s.resolved_checkpoint_backend == "memory"
    assert s.database_configured is False


def test_explicit_backend_overrides_auto():
    s = Settings(database_url="postgresql://u:p@h/db", checkpoint_backend="memory")
    assert s.resolved_checkpoint_backend == "memory"
