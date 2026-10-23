"""Explicit legacy recovery; refuses unknown schemas and unverified backups."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from alembic import command
from sqlalchemy import create_engine, text

from app.config import get_settings
from app.migration_support import acquire_migration_lock
from app.schema_contract import BACKEND, CANONICAL_HEAD, RECOVERY_BASE_HEAD, LEGACY_HEAD, differences, inventory
from scripts.database_evidence import control_evidence, digest, file_digest, identity, migration_config, snapshot, source_digest

RECOVERY_HEAD = "20260928_legacy01"


def source_checksums():
    provenance = json.loads((BACKEND / "alembic_legacy" / "provenance.json").read_text())
    result = {}
    for name, entry in provenance["files"].items():
        actual = source_digest(BACKEND / "alembic_legacy" / "versions" / name)
        if actual != entry["sha256"]:
            raise ValueError(f"Recovered migration provenance checksum mismatch: {name}")
        result[f"legacy/{name}"] = actual
    for directory in ["alembic", "alembic_legacy"]:
        for path in sorted((BACKEND / directory / "versions").glob("*.py")):
            result[f"{directory}/{path.name}"] = source_digest(path)
    for relative in ["alembic/env.py", "alembic_legacy/env.py", "app/models.py",
                     "app/schema_contract.py", "app/migration_support.py",
                     "scripts/reconcile_database.py", "scripts/database_evidence.py"]:
        result[relative] = source_digest(BACKEND / relative)
    for path in sorted((BACKEND / "app" / "schema_contracts").glob("*.json")):
        result[f"app/schema_contracts/{path.name}"] = source_digest(path)
    return result


def preflight(connection, manifest=None, *, rehearsal=False, require_rehearsal=False):
    errors = differences(connection, LEGACY_HEAD)
    if errors:
        raise ValueError("Legacy preflight refused: " + "; ".join(errors))
    # Constraints do not cover trust scores in the legacy schema.
    bad = connection.scalar(text("SELECT count(*) FROM devices WHERE trust_score NOT IN ('low','medium','high')"))
    if bad:
        raise ValueError("Legacy device trust scores require manual remediation")
    before = snapshot(connection)
    if manifest is not None:
        if manifest.get("format") != 1 or not manifest.get("restore_verified"):
            raise ValueError("A verified custom-format backup restoration is required")
        if manifest.get("source_control") != control_evidence(connection):
            raise ValueError("Backup must prove preservation of the original Alembic control-table state")
        if file_digest(manifest["dump_path"]) != manifest["dump_sha256"]:
            raise ValueError("Backup dump checksum mismatch")
        if manifest["source_identity"] == manifest["restored_identity"]:
            raise ValueError("Backup must be restored into a distinct database")
        expected_identity = manifest["restored_identity"] if rehearsal else manifest["source_identity"]
        if identity(connection) != expected_identity:
            raise ValueError("Backup manifest belongs to a different database")
        if before != manifest["snapshot"] or digest(inventory(connection)) != manifest["source_schema_sha256"]:
            raise ValueError("Source data/schema changed since verified backup")
        if require_rehearsal and (not manifest.get("rehearsal_verified") or manifest.get("rehearsal_migration_checksums") != source_checksums()):
            raise ValueError("The same migration code must pass recovery rehearsal before source apply")
    return before


def recover(connection, manifest, *, rehearsal=False):
    """Caller owns transaction. No commit, stamp, or destructive reset here."""
    acquire_migration_lock(connection)
    # Blocks writes from clients that do not participate in the advisory lock.
    connection.execute(text("LOCK TABLE alembic_version, audit_logs, users, courses, course_tas, enrollments, sessions, devices, checkins IN ACCESS EXCLUSIVE MODE"))
    checksums = source_checksums()
    before = preflight(connection, manifest, rehearsal=rehearsal, require_rehearsal=not rehearsal)
    config = migration_config(connection, legacy=True)
    config.attributes["verified_recovery"] = True
    command.upgrade(config, RECOVERY_HEAD)
    errors = differences(connection, RECOVERY_BASE_HEAD, check_revision=False)
    if errors:
        raise ValueError("Recovery destination is not canonical: " + "; ".join(errors))
    columns = {name: evidence["columns"] for name, evidence in before.items()}
    if snapshot(connection, columns) != before:
        raise ValueError("Original records changed during recovery")
    audit_id = str(uuid4())
    details = {"original_revision": LEGACY_HEAD, "recovery_revision": RECOVERY_HEAD,
               "canonical_revision": CANONICAL_HEAD, "backup_id": manifest["backup_id"],
               "backup_sha256": manifest["dump_sha256"], "migration_checksums": checksums,
               "preservation_sha256": digest(before), "schema_sha256": digest(inventory(connection)),
               "rows": {name: item["rows"] for name, item in before.items()}, "rehearsal": rehearsal}
    connection.execute(text("INSERT INTO audit_logs (id,action,resource_type,details,success,timestamp) VALUES (:id,'database.schema_reconciled','database',:details,true,:timestamp)"),
                       {"id": audit_id, "details": json.dumps(details, sort_keys=True), "timestamp": datetime.now(timezone.utc)})
    changed = connection.execute(text("UPDATE alembic_version SET version_num=:target WHERE version_num=:source"),
                                 {"target": RECOVERY_BASE_HEAD, "source": RECOVERY_HEAD})
    if changed.rowcount != 1:
        raise ValueError("Recovery revision transition did not update exactly one row")
    canonical = migration_config(connection)
    command.upgrade(canonical, "head")
    if differences(connection) or snapshot(connection, columns, exclude_audit_id=audit_id) != before:
        raise ValueError("Final schema/data verification failed")
    command.current(canonical, verbose=True)
    command.check(canonical)
    command.upgrade(canonical, "head")
    return {"audit_id": audit_id, "canonical_revision": CANONICAL_HEAD,
            "preserved_rows": details["rows"], "migration_checksums": checksums}


def run(url, manifest_path=None, *, apply=False, rehearsal=False):
    path = Path(manifest_path).resolve() if manifest_path else None
    manifest = json.loads(path.read_text()) if path else None
    if apply and manifest is None:
        raise ValueError("Apply requires a verified backup manifest")
    if rehearsal and manifest is None:
        raise ValueError("Rehearsal requires a verified backup manifest")
    source_checksums()
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            if apply:
                result = recover(connection, manifest, rehearsal=rehearsal)
            else:
                connection.execute(text("SET TRANSACTION READ ONLY"))
                before = preflight(connection, manifest, rehearsal=rehearsal)
                result = {"dry_run": True, "source_revision": LEGACY_HEAD,
                          "target_revision": CANONICAL_HEAD, "rows": {n: e["rows"] for n, e in before.items()}}
        if apply and rehearsal:
            manifest["rehearsal_verified"] = True
            manifest["rehearsal_result"] = result
            manifest["rehearsal_migration_checksums"] = result["migration_checksums"]
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            temporary.replace(path)
        return result
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-manifest")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rehearsal", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(get_settings().database_url, args.backup_manifest, apply=args.apply, rehearsal=args.rehearsal), indent=2))


if __name__ == "__main__":
    main()
