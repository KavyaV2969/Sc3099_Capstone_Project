"""Read-only, frozen PostgreSQL schema verification, including checks and defaults.

Contracts are generated from independently migrated PostgreSQL databases, never
from an incompatible database that is being repaired. They are shipped with app.
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path

from alembic.script import ScriptDirectory
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select, text

from app.models import Base

CANONICAL_HEAD = "20260929_0009"
RECOVERY_BASE_HEAD = "20260928_0006"
LEGACY_HEAD = "20260911_0007"
CONTRACT_DIR = Path(__file__).with_name("schema_contracts")
BACKEND = Path(__file__).resolve().parents[1]


def _normalize(value):
    if not isinstance(value, str):
        return value
    # SQL identifiers/keywords are case-insensitive; quoted values are not.
    pieces = re.split(r"('(?:''|[^'])*')", value.strip())
    return "".join(piece if n % 2 else re.sub(r"\s+", " ", piece).lower()
                   for n, piece in enumerate(pieces))


def _normalize_check(value):
    value = _normalize(value)
    # pg_dump moves a varchar array's text coercion to each array item. These
    # two catalog expressions are equivalent for the application's VARCHARs.
    pieces = re.split(r"('(?:''|[^'])*')", value)
    for n in range(0, len(pieces), 2):
        pieces[n] = pieces[n].replace("::character varying::text", "::character varying").replace("]::text[]", "]")
    return "".join(pieces)


def inventory(connection):
    """Capture all public application structures; omit Alembic's control table."""
    if connection.dialect.name != "postgresql":
        raise ValueError("Frozen schema contracts require PostgreSQL")
    inspector = inspect(connection)
    result = {}
    for name in sorted(set(inspector.get_table_names(schema="public")) - {"alembic_version"}):
        columns = {
            c["name"]: {"type": str(c["type"].compile(dialect=connection.dialect)).lower(),
                        "nullable": c["nullable"], "default": _normalize(c["default"])}
            for c in inspector.get_columns(name, schema="public")
        }
        pk = inspector.get_pk_constraint(name, schema="public")
        fks = [{"name": f["name"], "columns": f["constrained_columns"],
                "table": f["referred_table"], "schema": f["referred_schema"] or "public",
                "referred_columns": f["referred_columns"], "options": f["options"]}
               for f in inspector.get_foreign_keys(name, schema="public")]
        uniques = [{"name": u["name"], "columns": u["column_names"]}
                   for u in inspector.get_unique_constraints(name, schema="public")]
        checks = [{"name": c["name"], "expression": _normalize_check(c["sqltext"])}
                  for c in inspector.get_check_constraints(name, schema="public")]
        indexes = [{"name": i["name"], "columns": i["column_names"], "unique": i["unique"],
                    "expressions": i.get("expressions"), "include": i.get("include_columns", []),
                    "options": i.get("dialect_options", {})}
                   for i in inspector.get_indexes(name, schema="public") if not i.get("duplicates_constraint")]
        result[name] = {"columns": columns, "primary_key": pk["constrained_columns"],
                        "foreign_keys": sorted(fks, key=lambda x: x["name"]),
                        "unique_constraints": sorted(uniques, key=lambda x: x["name"]),
                        "checks": sorted(checks, key=lambda x: x["name"]),
                        "indexes": sorted(indexes, key=lambda x: x["name"])}
    return result


def load_contract(revision=CANONICAL_HEAD):
    data = json.loads((CONTRACT_DIR / f"{revision}.json").read_text(encoding="utf-8"))
    if data["revision"] != revision or data["dialect"] != "postgresql":
        raise ValueError("Invalid frozen schema contract")
    return data


def object_inventory(connection):
    """Freeze definitions and enabled state, not merely the presence of a trigger."""
    triggers = connection.execute(text("""
        SELECT c.relname, t.tgname, t.tgenabled, pg_get_triggerdef(t.oid)
        FROM pg_trigger t JOIN pg_class c ON t.tgrelid=c.oid
        WHERE c.relnamespace='public'::regnamespace AND NOT t.tgisinternal
        ORDER BY c.relname,t.tgname
    """)).all()
    functions = connection.execute(text("""
        SELECT DISTINCT p.proname, pg_get_functiondef(p.oid)
        FROM pg_proc p JOIN pg_trigger t ON t.tgfoid=p.oid
        JOIN pg_class c ON t.tgrelid=c.oid
        WHERE c.relnamespace='public'::regnamespace AND NOT t.tgisinternal
        ORDER BY p.proname
    """)).all()
    return {"triggers": [[table, name, enabled, _normalize(ddl)] for table, name, enabled, ddl in triggers],
            "functions": [[name, _normalize(ddl)] for name, ddl in functions]}


def differences(connection, revision=CANONICAL_HEAD, *, check_revision=True):
    contract = load_contract(revision)
    expected = contract["tables"]
    actual = inventory(connection)
    errors = []
    for table in sorted(set(expected) | set(actual)):
        if table not in expected:
            errors.append(f"Unexpected table: {table}")
        elif table not in actual:
            errors.append(f"Missing table: {table}")
        else:
            for component in expected[table]:
                if expected[table][component] != actual[table][component]:
                    errors.append(f"{table}: incompatible {component}")
    inspector = inspect(connection)
    if inspector.has_table("alembic_version", schema="public"):
        columns = inspector.get_columns("alembic_version", schema="public")
        if (len(columns) != 1 or columns[0]["name"] != "version_num"
                or str(columns[0]["type"]).lower() != "varchar(32)"
                or columns[0]["nullable"] or columns[0]["default"] is not None
                or inspector.get_pk_constraint("alembic_version", schema="public")["constrained_columns"] != ["version_num"]):
            errors.append("Incompatible Alembic control-table structure")
    else:
        errors.append("Missing Alembic control table")
    if check_revision:
        versions = list(connection.scalars(text("SELECT version_num FROM alembic_version"))) if inspector.has_table("alembic_version") else []
        if versions != [revision]:
            errors.append("Alembic revision is missing, unknown, multiple, or not the expected head")
    invalid = connection.execute(text("""
        SELECT conrelid::regclass::text, conname FROM pg_constraint
        WHERE connamespace = 'public'::regnamespace AND NOT convalidated
        UNION ALL
        SELECT indrelid::regclass::text, indexrelid::regclass::text
        FROM pg_index JOIN pg_class ON indrelid = pg_class.oid
        WHERE relnamespace = 'public'::regnamespace AND (NOT indisvalid OR NOT indisready)
    """)).all()
    errors.extend(f"Invalid constraint/index: {t}.{n}" for t, n in invalid)
    if inspect(connection).get_view_names(schema="public") or inspect(connection).get_materialized_view_names(schema="public"):
        errors.append("Unexpected public views")
    if object_inventory(connection) != contract.get("objects", {"triggers": [], "functions": []}):
        errors.append("Incompatible public triggers/functions")
    if connection.scalar(text("SELECT count(*) FROM pg_type WHERE typnamespace='public'::regnamespace AND typtype='e'")):
        errors.append("Unexpected public enum types")
    return errors


def canonical_graph_is_valid():
    config = Config()
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return ScriptDirectory.from_config(config).get_heads() == [CANONICAL_HEAD]


@dataclass(frozen=True)
class DatabaseReadiness:
    connected: bool
    schema: str
    errors: tuple[str, ...] = ()

    @property
    def healthy(self):
        return self.connected and self.schema == "healthy"


def inspect_readiness(engine):
    connected = False
    try:
        with engine.connect() as connection:
            if connection.dialect.name == "postgresql":
                connection.execute(text("SET TRANSACTION READ ONLY"))
                connection.execute(text("SET LOCAL statement_timeout = '5s'"))
                connection.execute(text("SET LOCAL lock_timeout = '2s'"))
            connection.execute(text("SELECT 1"))
            connected = True
            if not canonical_graph_is_valid():
                return DatabaseReadiness(True, "incompatible", ("Canonical revision graph does not match the application contract",))
            errors = differences(connection)
            if not errors:
                context = MigrationContext.configure(connection, opts={"compare_type": True, "compare_server_default": True})
                if compare_metadata(context, Base.metadata):
                    errors.append("ORM metadata differs from the supported PostgreSQL schema")
            if not errors:
                for table in Base.metadata.sorted_tables:
                    connection.execute(select(table).limit(0))
            return DatabaseReadiness(True, "incompatible" if errors else "healthy", tuple(errors))
    except Exception as exc:
        # The exception class is useful for diagnosis without logging credentials/SQL.
        return DatabaseReadiness(connected, "unknown", (f"Schema verification failed: {type(exc).__name__}",))
