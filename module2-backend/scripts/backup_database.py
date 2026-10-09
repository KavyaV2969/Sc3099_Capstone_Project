"""Create a custom-format backup and prove restoration into a distinct database.

Docker transport is optional; PostgreSQL CLI tools can also be used directly.
"""
import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.schema_contract import inventory
from scripts.database_evidence import control_evidence, create_isolated_database, digest, file_digest, identity, snapshot


def create_backup(source_url, output_dir, restore_database, docker_container=None):
    directory = Path(output_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    backup_id = str(uuid4())
    dump_path = directory / f"{backup_id}.dump"
    manifest_path = directory / f"{backup_id}.json"
    source = make_url(source_url)
    engine = create_engine(source)
    try:
        with engine.connect() as connection:
            before = snapshot(connection)
            schema = inventory(connection)
            source_identity = identity(connection)
            control = control_evidence(connection)
        env = os.environ.copy()
        env["PGPASSWORD"] = source.password or ""
        if docker_container:
            # Verify transport actually points at the selected source cluster/database.
            output = subprocess.check_output(["docker", "exec", docker_container, "psql", "-U", source.username, "-d", source.database, "-At", "-c", "SELECT system_identifier::text FROM pg_control_system()"])
            if output.decode().strip() != source_identity["cluster_id"]:
                raise ValueError("Docker container does not contain the source PostgreSQL cluster")
            prefix = ["docker", "exec", docker_container]
            dump_cmd = prefix + ["pg_dump", "-U", source.username, "-d", source.database]
        else:
            dump_cmd = ["pg_dump", "-h", source.host, "-p", str(source.port or 5432), "-U", source.username, "-d", source.database]
        with dump_path.open("xb") as output:
            subprocess.run(dump_cmd + ["--format=custom", "--no-owner", "--no-acl"], stdout=output, env=env, check=True)
        target_url = create_isolated_database(source_url, restore_database)
        if docker_container:
            restore_cmd = ["docker", "exec", "-i", docker_container, "pg_restore", "-U", source.username, "-d", restore_database]
        else:
            restore_cmd = ["pg_restore", "-h", source.host, "-p", str(source.port or 5432), "-U", source.username, "-d", restore_database]
        with dump_path.open("rb") as stream:
            subprocess.run(restore_cmd + ["--exit-on-error", "--single-transaction", "--no-owner", "--no-acl"], stdin=stream, env=env, check=True)
        restored = create_engine(target_url)
        try:
            with restored.connect() as connection:
                restored_identity = identity(connection)
                if snapshot(connection) != before or inventory(connection) != schema or control_evidence(connection) != control:
                    raise ValueError("Restored database does not match source data and schema")
        finally:
            restored.dispose()
        with engine.connect() as connection:
            if snapshot(connection) != before or inventory(connection) != schema or control_evidence(connection) != control:
                raise ValueError("Source changed while backing up; stop writers and retry")
        manifest = {"format": 1, "backup_id": backup_id, "created_at": datetime.now(timezone.utc).isoformat(),
                    "dump_path": str(dump_path), "dump_sha256": file_digest(dump_path),
                    "source_identity": source_identity, "source_schema_sha256": digest(schema),
                    "source_control": control,
                    "snapshot": before, "restored_identity": restored_identity,
                    "restore_verified": True, "rehearsal_verified": False}
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return manifest_path
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--restore-database", required=True)
    parser.add_argument("--docker-container")
    args = parser.parse_args()
    print(create_backup(get_settings().database_url, args.output_dir, args.restore_database, args.docker_container))


if __name__ == "__main__":
    main()
