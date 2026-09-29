"""Generate a contract only from an independently migrated EMPTY database.

Creates a new saiv_f00_ database; never snapshots an existing live database as the
desired schema. Review/commit the resulting contract with its migration changes.
"""
import argparse
import json

from alembic import command
from sqlalchemy import create_engine, text

from app.config import get_settings
from app.schema_contract import CANONICAL_HEAD, LEGACY_HEAD, CONTRACT_DIR, inventory, object_inventory
from scripts.database_evidence import create_isolated_database, migration_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--legacy", action="store_true")
    args = parser.parse_args()
    revision = LEGACY_HEAD if args.legacy else CANONICAL_HEAD
    engine = create_engine(create_isolated_database(get_settings().database_url, args.database))
    try:
        with engine.begin() as connection:
            command.upgrade(migration_config(connection, legacy=args.legacy), revision)
            if not args.legacy:
                command.check(migration_config(connection))
            tables = inventory(connection)
            quote = connection.dialect.identifier_preparer.quote
            if any(connection.scalar(text("SELECT count(*) FROM " + quote(name))) for name in tables):
                raise ValueError("Contracts must be generated from empty application tables")
            contract = {"revision": revision, "dialect": "postgresql",
                        "generated_from": "empty PostgreSQL 15 database using frozen migrations", "tables": tables,
                        "objects": object_inventory(connection)}
        CONTRACT_DIR.mkdir(exist_ok=True)
        path = CONTRACT_DIR / f"{revision}.json"
        path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(path)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
