"""Read-only verification of revision, structures and normal ORM projections."""
import json

from sqlalchemy import create_engine
from app.config import get_settings
from app.schema_contract import inspect_readiness


def main():
    engine = create_engine(get_settings().database_url)
    try:
        result = inspect_readiness(engine)
        print(json.dumps({"healthy": result.healthy, "connected": result.connected,
                          "schema": result.schema, "errors": result.errors}, indent=2))
        raise SystemExit(0 if result.healthy else 1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
