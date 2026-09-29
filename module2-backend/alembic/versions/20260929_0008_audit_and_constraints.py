"""Enforce audit immutability and completion field invariants.

Revision ID: 20260929_0008
Revises: 20260929_0007
"""
from alembic import op

revision = "20260929_0008"
down_revision = "20260929_0007"
branch_labels = depends_on = None

CHECKS = {
    "users": {"ck_users_failed_attempts": "failed_login_attempts >= 0",
              "ck_users_activation_pair": "(activation_token_hash IS NULL) = (activation_expires_at IS NULL)"},
    "devices": {"ck_devices_checkin_count": "total_checkins >= 0",
                "ck_devices_revocation": "revoked_at IS NULL OR (is_active = false AND is_trusted = false)"},
}


def upgrade():
    for table, checks in CHECKS.items():
        with op.batch_alter_table(table) as batch:
            for name, expression in checks.items():
                batch.create_check_constraint(name, expression)
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION public.reject_audit_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN
              RAISE EXCEPTION 'audit logs are append-only' USING ERRCODE = '42501';
            END; $$""")
        op.execute("""CREATE TRIGGER audit_logs_append_only
            BEFORE UPDATE OR DELETE OR TRUNCATE ON public.audit_logs
            FOR EACH STATEMENT EXECUTE FUNCTION public.reject_audit_mutation()""")
        op.execute("ALTER TABLE public.audit_logs ENABLE ALWAYS TRIGGER audit_logs_append_only")


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER audit_logs_append_only ON public.audit_logs")
        op.execute("DROP FUNCTION public.reject_audit_mutation()")
    for table, checks in reversed(list(CHECKS.items())):
        with op.batch_alter_table(table) as batch:
            for name in checks:
                batch.drop_constraint(name, type_="check")
