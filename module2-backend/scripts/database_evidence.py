"""Privacy-preserving schema/data evidence and isolated database helpers."""
import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.schema_contract import BACKEND, inventory
from alembic.config import Config


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def source_digest(path):
    """Stable textual source checksum across Git's Windows newline conversion."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def identity(connection):
    row = connection.execute(text("SELECT current_database() AS database, (SELECT oid::text FROM pg_database WHERE datname=current_database()) AS database_oid, (SELECT system_identifier::text FROM pg_control_system()) AS cluster_id")).mappings().one()
    return dict(row)


def control_evidence(connection):
    """Backup evidence must preserve Alembic's state as well as application data."""
    inspector = inspect(connection)
    if not inspector.has_table("alembic_version"):
        return None
    return {"versions": sorted(connection.scalars(text("SELECT version_num FROM alembic_version"))),
            "columns": [{"name": column["name"], "type": str(column["type"]),
                         "nullable": column["nullable"], "default": column["default"]}
                        for column in inspector.get_columns("alembic_version")],
            "primary_key": inspector.get_pk_constraint("alembic_version")["constrained_columns"]}


def _value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return value


def snapshot(connection, columns=None, exclude_audit_id=None):
    inspector = inspect(connection)
    if columns is None:
        columns = {name: sorted(c["name"] for c in inspector.get_columns(name))
                   for name in inspector.get_table_names() if name != "alembic_version"}
    result = {}
    quote = connection.dialect.identifier_preparer.quote
    for name, names in sorted(columns.items()):
        pk = inspector.get_pk_constraint(name)["constrained_columns"]
        if not pk:
            raise ValueError(f"Cannot prove preservation without a primary key: {name}")
        query = f"SELECT {', '.join(map(quote, names))} FROM {quote(name)}"
        args = {}
        if name == "audit_logs" and exclude_audit_id:
            query += " WHERE id != :audit_id"
            args["audit_id"] = exclude_audit_id
        query += " ORDER BY " + ", ".join(map(quote, pk))
        data_hash, key_hash = hashlib.sha256(), hashlib.sha256()
        count = 0
        rows = connection.execute(text(query), args)
        for row in rows.mappings():
            values = [_value(row[n]) for n in names]
            data_hash.update(json.dumps(values, sort_keys=True, separators=(",", ":")).encode() + b"\n")
            key_hash.update(json.dumps([_value(row[n]) for n in pk], separators=(",", ":")).encode() + b"\n")
            count += 1
        result[name] = {"columns": names, "rows": count, "values_sha256": data_hash.hexdigest(), "primary_keys_sha256": key_hash.hexdigest()}
    return result


def migration_config(connection=None, *, legacy=False, database_url=None):
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / ("alembic_legacy" if legacy else "alembic")))
    if connection is not None:
        config.attributes["connection"] = connection
    if database_url:
        config.attributes["database_url"] = database_url
    return config


def isolated_url(source_url, name):
    source = make_url(source_url)
    if not re.fullmatch(r"saiv_f00_[a-z0-9_]+", name) or name == source.database:
        raise ValueError("Isolated database must use a distinct saiv_f00_ name")
    return source.set(database=name)


def create_isolated_database(source_url, name):
    target = isolated_url(source_url, name)
    admin = create_engine(make_url(source_url).set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            # Name has been validated; quote the identifier instead of interpolating SQL text.
            quoted = connection.dialect.identifier_preparer.quote(name)
            connection.execute(text(f"CREATE DATABASE {quoted}"))
    finally:
        admin.dispose()
    return target
