"""Alembic migrations must apply cleanly and match the ORM metadata."""

import os

import pytest
from sqlalchemy import create_engine, inspect

pytestmark = pytest.mark.integration

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture
def sqlite_url(tmp_path, monkeypatch):
    db_path = tmp_path / "mig.sqlite3"
    url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    from security.config import get_settings

    get_settings.cache_clear()
    yield url
    get_settings.cache_clear()


def _alembic_config():
    from alembic.config import Config

    cfg = Config(os.path.join(PROJECT_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(PROJECT_ROOT, "database/migrations"))
    return cfg


def test_upgrade_head_creates_operational_tables(sqlite_url):
    from alembic import command

    command.upgrade(_alembic_config(), "head")

    tables = set(inspect(create_engine(sqlite_url)).get_table_names())
    assert {"job", "audit_log", "alembic_version"} <= tables


def test_downgrade_base_is_clean(sqlite_url):
    from alembic import command

    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    tables = set(inspect(create_engine(sqlite_url)).get_table_names())
    assert "job" not in tables
    assert "audit_log" not in tables


def test_migration_matches_orm_metadata(sqlite_url):
    """Tables created by migrations must have the same columns as the ORM models."""
    from alembic import command

    import database.models  # noqa: F401
    from database.base import Base

    command.upgrade(_alembic_config(), "head")
    insp = inspect(create_engine(sqlite_url))

    for table_name, table in Base.metadata.tables.items():
        migrated_cols = {c["name"] for c in insp.get_columns(table_name)}
        orm_cols = {c.name for c in table.columns}
        assert orm_cols == migrated_cols, f"column drift in {table_name}"
