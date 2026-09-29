# F00 PostgreSQL recovery and verification

This runbook implements the approved data-preserving recovery. Apply grading
clarifications, Security Requirements, API Specification and recommended design
in that order. This repairs migration/schema compatibility; it does not close the
other backend audit findings.

## Cause and preserved history

On September 11, locally created, uncommitted migrations `20260911_0005`,
`20260911_0006`, and `20260911_0007` were applied to PostgreSQL. September 15 cleanup
deleted those migration files while the persistent PostgreSQL volume retained
their changes and revision. The canonical checkout instead branches from `0004`
to `20260915_0005`.

The recovered files and original prerequisites live in
`module2-backend/alembic_legacy/versions/`. `alembic_legacy/provenance.json` records
source session locations/timestamps and normalized textual SHA-256 checksums,
including the final `0007` amendment that removes/restores the default around
JSON/TEXT conversion. Normalized newlines make checksums stable across Windows
and Linux Git checkouts. PostgreSQL dump checksums always cover the exact bytes.

Canonical migration history is unchanged. Its new head is `20260928_0006`.
The separate legacy head `20260928_legacy01` applies the missing metadata,
constraints, defaults and indexes. It can run only through the recovery command.
Do not copy the legacy branch into the canonical migration directory or replay
the canonical `0005` against the legacy schema.

## Safety requirements

- Stop backend writers and retention workers before backing up or recovering.
- Use the configured PostgreSQL 15 instance. Set `DATABASE_URL` and the normal
  application `SECRET_KEY` in the process environment; never commit credentials.
- Operator tools need database creation/backup privileges and access to
  `pg_control_system()` to verify cluster identity. Application readiness uses
  ordinary schema/catalog read access and does not require operator privileges.
- Store backups/manifests privately. `tmp/f00-recovery/` is Git-ignored and contains
  personal data in its dump files. Restrict access and retain it for recovery.
- Each backup is restored into a new, distinctly named database; no database or
  table is deleted/reset as part of recovery.
- Recovery checks the source revision and frozen legacy schema, dump checksum,
  cluster/database identity, original data hashes, and rehearsal code checksums.
  Any discrepancy stops recovery before mutation.
- Recovery takes advisory lock `30990002` and exclusive application-table locks.
  Normal Alembic commands use the same advisory lock. Lock timeout is five seconds;
  statement timeout is 120 seconds. Concurrent operations fail safely.

## Commands

Run from `module2-backend`, with the virtual environment active. Replace example
database names with unique `saiv_f00_` names and use the manifest path printed by
the backup command. Recovery/verification tools are shipped in the backend image;
backup additionally requires local PostgreSQL CLI tools or host Docker transport.

Inspect the source without changing it:

```powershell
python -m scripts.reconcile_database
```

Create a custom-format dump and prove restoration into a separate database:

```powershell
python -m scripts.backup_database --output-dir ../tmp/f00-recovery/backup --restore-database saiv_f00_rehearsal_example --docker-container saiv-postgres
```

Omit `--docker-container` when `pg_dump` and `pg_restore` are installed locally.
The script verifies transport cluster identity, restored schema/data hashes and
that the source did not change during backup. It prints a manifest only on success.
Failed attempts retain their backup and any created rehearsal database for inspection.

Set `DATABASE_URL` to the new rehearsal database, then dry-run and apply there:

```powershell
python -m scripts.reconcile_database --backup-manifest <manifest-path> --rehearsal
python -m scripts.reconcile_database --backup-manifest <manifest-path> --rehearsal --apply
python -m scripts.verify_schema
alembic heads
alembic current -v
alembic check
alembic upgrade head
```

The successful rehearsal records code/contract checksums in the manifest. Do not
change recovery code, models, environments, contracts or migration files between
rehearsal and source apply. If they change, take a new verified backup and rehearse
the new code on its new restored database.

Restore `DATABASE_URL` to the original source, then apply:

```powershell
python -m scripts.reconcile_database --backup-manifest <manifest-path> --apply
python -m scripts.verify_schema
alembic current -v
alembic check
alembic upgrade head
```

The final source operation runs in one transaction: migration, exact target-schema
verification, original-column/primary-key hash verification, one audit insertion,
conditional recovery-version adoption, and canonical Alembic validation. Version
normalization happens only after structural equivalence is proved. No `stamp`,
history reset, table drop, device merge, truncation or fabricated key is used.

The audit action is `database.schema_reconciled`. Its details preserve original,
recovery and canonical revisions, backup ID/checksum, migration/code checksums,
schema/preservation hashes and original row counts. An exception rolls back all
DDL, backfills, the audit event and the revision transition.

Keep traffic stopped until post-commit schema verification and a normal
`select(Checkin).limit(1)` query succeed. Then resume the chosen deployment.

## Readiness and device compatibility

`GET /health` returns HTTP 200 only when database connectivity, the frozen canonical
schema, current ORM metadata and Redis all pass. It preserves existing fields and
adds `schema: healthy|incompatible|unknown`. Failures return 503 and generic public
state; server logs contain schema component diagnostics without raw SQL/credentials.
Each request performs read-only verification with bounded timeouts and no cached
healthy result. Invalid/unvalidated constraints/indexes and unknown revisions fail.
Retention startup is skipped when the schema is incompatible. The production image
uses this endpoint for its Docker health check.

Device storage uses a globally unique 64-character fingerprint; nullable name and
platform; platform width 50; trust width 20; required last-seen time; and documented
user/activity/trust indexes. New registration initializes last-seen and requires a
nonblank key. Registration conflicts and races return controlled HTTP 400.

Two legacy NULL public keys remain unchanged. Their owners must supply real keys;
only then may a later migration enforce `devices.public_key NOT NULL`. Collecting
keys and broader attestation/cryptographic-proof work are separate completion items.

## Regression verification

```powershell
python -m pytest tests -q
$env:F00_POSTGRES_TEST_URL = $env:DATABASE_URL
$env:F00_BACKUP_MANIFEST = '<verified-manifest-path>'
python -m pytest tests/test_f00_postgresql.py -q
```

Use the manifest while its rehearsal database is still at the original legacy
revision. Restored-data regression tests roll their changes back; the subsequent
operator rehearsal commits them explicitly. PostgreSQL tests create disposable
`saiv_f00_test_` databases and only delete their own generated test databases during
teardown. They never write to the source database.

Coverage includes fresh migration, recovered history reproduction, existing
canonical-device preservation, unsafe conversion rejection, invalid indexes,
constraint/type/default/index/revision drift, duplicate registrations/races,
FK deletion actions, ORM operations, lock contention and injected recovery failure.

Frozen contracts are generated independently using:

```powershell
python -m scripts.freeze_schema_contract --database saiv_f00_contract_example
python -m scripts.freeze_schema_contract --database saiv_f00_legacy_contract_example --legacy
```

This tool creates a new empty database, migrates it and verifies it before writing
a contract. Never redefine the expected schema by copying the drifted source.

## Rollback

Any pre-commit failure is automatically rolled back. Recheck the original revision,
schema and preservation evidence before retrying. Legacy reconciliation is
forward-only. If post-commit recovery is required, restore the verified dump into
a separate database and deliberately switch configuration after validating it;
retain the original database for investigation. Do not invoke historical destructive
downgrades on the existing attendance database.

## Execution evidence

Completed on 28 September 2026 against PostgreSQL 15.19:

- Full backend suite: **173 passed**, including **35 real PostgreSQL tests**.
- Independently empty PostgreSQL migrated to `20260928_0006`; reconstructed legacy
  migrations reproduced the observed legacy schema.
- Final custom-format backup ID: `0dda9a3b-74d3-4c41-9468-94b03972ca09`. Dump and
  manifest are under the private Git-ignored `tmp/f00-recovery/backup/` directory.
  Restoration proved matching application data/schema and Alembic control state.
- Rehearsal committed in `saiv_f00_rehearsal_20260928_r3`, followed by successful
  recovery of the existing `saiv` database using the same verified code.
- Source revision is now `20260928_0006`; `alembic heads`, `current -v`, `check`,
  repeated `upgrade head`, and the independent schema verifier all succeeded.
- All original column values and primary-key sets matched the backup hashes.
  Counts remain 403 users, 99 courses, 77 sessions, 41 enrollments, 4 devices,
  9 check-ins and 0 course TA assignments. Audit rows changed from 1,237 to 1,238
  through exactly one recovery event, ID `6cb09bfe-69a8-431d-84d4-043289f16279`.
- Both legacy NULL public keys remain unchanged. A normal ORM `Checkin` query
  succeeds against the reconciled source.
- `/health` returned 503/schema incompatible before source recovery and 200/schema
  healthy afterward with real Redis. The built production image passed schema
  verification against both fresh and existing databases.
- A temporary production-image container performed normal startup, served a real
  HTTP 200 on localhost port 18002, and reached Docker health state `healthy`.
  Retention was disabled for this verification; the temporary container was stopped
  and removed. The previously stopped regular backend deployment was not started.

Detailed private evidence is in `tmp/f00-recovery/source-result.json`,
`rehearsal-result.json`, the final backup manifest and `tests.xml`.

F00 is resolved. Owner-supplied public keys and later database NOT NULL enforcement
remain tracked follow-up work; the other backend audit findings remain outside
this change.
# Forward completion migration — 29 September 2026

The dated recovery evidence below remains the historical baseline at
`20260928_0006`. Current readiness requires `20260929_0008`. Legacy recovery
first verifies the historical destination and its preserved rows, then applies
the two new canonical completion migrations. The current contract additionally
checks the audit trigger/function definitions and enabled state. See
[completion contract](BACKEND-COMPLETION.md) for current deployment and evidence.

