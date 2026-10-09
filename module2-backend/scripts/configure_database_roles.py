"""Provision restricted backend and optional read-only dashboard identities.

Run with DATABASE_URL set to the migration/operator URL. Credential URLs are
read from BACKEND_DATABASE_URL and optional DASHBOARD_DATABASE_URL; never printed.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from psycopg2 import sql
from app.config import get_settings


def configure(connection, operator_url, application_url, dashboard_url=None):
    operator = make_url(operator_url)
    targets = [(make_url(application_url), False)]
    if dashboard_url:
        targets.append((make_url(dashboard_url), True))
    names = [url.username for url, _ in targets]
    if len(set(names)) != len(names) or operator.username in names:
        raise ValueError("Operator, application and dashboard roles must be distinct")
    for url, _ in targets:
        if not url.username or not url.password or url.database != operator.database:
            raise ValueError("Restricted URLs require credentials for the same database")
    cursor = connection.connection.driver_connection.cursor()
    try:
        cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        for url, readonly in targets:
            role = sql.Identifier(url.username)
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (url.username,))
            if cursor.fetchone() is None:
                cursor.execute(sql.SQL("CREATE ROLE {} LOGIN").format(role))
            cursor.execute("""SELECT EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname=%s)
                OR EXISTS(SELECT 1 FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner WHERE r.rolname=%s)
                OR EXISTS(SELECT 1 FROM pg_namespace n JOIN pg_roles r ON r.oid=n.nspowner WHERE r.rolname=%s)""",
                (url.username, url.username, url.username))
            if cursor.fetchone()[0]:
                raise ValueError("Restricted roles must not own objects or have role memberships")
            cursor.execute(sql.SQL("ALTER ROLE {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}")
                           .format(role, sql.Literal(url.password)))
            cursor.execute(sql.SQL("ALTER ROLE {} IN DATABASE {} SET search_path=public,pg_catalog")
                           .format(role, sql.Identifier(operator.database)))
            cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(operator.database), role))
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
            cursor.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(role))
            if readonly:
                for table in ("courses", "course_tas", "enrollments", "sessions", "checkins", "devices"):
                    cursor.execute(sql.SQL("GRANT SELECT ON {} TO {}").format(sql.Identifier(table), role))
                cursor.execute(sql.SQL("GRANT SELECT (id,email,full_name,role,is_active,face_enrolled,created_at,updated_at) ON users TO {}").format(role))
            else:
                cursor.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {}").format(role))
                cursor.execute(sql.SQL("REVOKE UPDATE,DELETE,TRUNCATE ON audit_logs FROM {}").format(role))
                cursor.execute(sql.SQL("REVOKE ALL ON alembic_version FROM {}").format(role))
                cursor.execute(sql.SQL("GRANT SELECT ON alembic_version TO {}").format(role))
    finally:
        cursor.close()


def main():
    settings = get_settings()
    engine = create_engine(settings.database_url)
    try:
        with engine.begin() as connection:
            configure(connection, settings.database_url, os.environ["BACKEND_DATABASE_URL"],
                      os.environ.get("DASHBOARD_DATABASE_URL") or None)
        print("Restricted database roles configured")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
