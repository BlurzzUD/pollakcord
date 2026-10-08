import asyncio
import sqlite3
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app.db.base import Base

BACKEND = Path(__file__).resolve().parent.parent


def alembic_config(url: str) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def test_migrations_build_exactly_the_schema_the_models_describe(tmp_path):
    database = tmp_path / "migrated.db"
    command.upgrade(alembic_config(f"sqlite+aiosqlite:///{database}"), "head")
    engine = create_engine(f"sqlite:///{database}")
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    engine.dispose()
    assert differences == []


def test_migration_seeds_the_school_classes(tmp_path):
    database = tmp_path / "seeded.db"
    command.upgrade(alembic_config(f"sqlite+aiosqlite:///{database}"), "head")
    connection = sqlite3.connect(database)
    codes = [row[0] for row in connection.execute("SELECT code FROM school_classes ORDER BY sort_order")]
    connection.close()
    assert codes == ["9A", "9B", "10A", "10B", "11A", "11B", "12A", "12B", "13A", "13B", "14A", "14B"]


def test_migrations_are_reversible(tmp_path):
    database = tmp_path / "reversible.db"
    config = alembic_config(f"sqlite+aiosqlite:///{database}")
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    connection = sqlite3.connect(database)
    tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    connection.close()
    assert tables == ["alembic_version"]
    command.upgrade(config, "head")
