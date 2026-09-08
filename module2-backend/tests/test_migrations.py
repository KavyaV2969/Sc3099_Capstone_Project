"""Exercise the frozen Alembic migration independently of ORM create_all."""
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app import config as app_config
from app.models import Base

BACKEND = Path(__file__).resolve().parents[1]


def migration_config(output=None):
    config = Config(str(BACKEND / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def test_migration_upgrade_matches_models_and_downgrades(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"
    monkeypatch.setattr(app_config, "get_settings", lambda: SimpleNamespace(database_url=url))
    config = migration_config()
    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        assert set(inspect(connection).get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
    command.downgrade(config, "20260825_0001")
    assert set(inspect(engine).get_table_names()) == {"users", "audit_logs", "alembic_version"}
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


def test_migration_generates_postgresql_sql(monkeypatch):
    monkeypatch.setattr(app_config, "get_settings", lambda: SimpleNamespace(database_url="postgresql://localhost/test"))
    output = StringIO()
    command.upgrade(migration_config(output), "head", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE checkins" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "uq_checkins_student_session" in sql
    assert "REFERENCES users (id)" in sql
