import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'module2-backend'))
os.environ.setdefault('SECRET_KEY', 'audit-only-placeholder-secret-over-32-characters')
os.environ['RETENTION_CLEANUP_ENABLED'] = 'false'

from sqlalchemy import inspect, text
from alembic.migration import MigrationContext
from alembic.autogenerate import compare_metadata
from app.db import engine
from app.models import Base
from app.main import app
from app.main import health_check
from app.models import Checkin
from sqlalchemy import select
from sqlalchemy.orm import Session

with engine.connect() as connection:
    print('revision:', connection.execute(text('SELECT version_num FROM alembic_version')).all())
    print('tables:', inspect(connection).get_table_names())
    print('schema_differences:', str(compare_metadata(MigrationContext.configure(connection), Base.metadata)))
    print('audit_triggers:', connection.execute(text("SELECT tgname FROM pg_trigger WHERE tgrelid = 'audit_logs'::regclass AND NOT tgisinternal")).all())
    print('db_role:', connection.execute(text('SELECT current_user, rolsuper FROM pg_roles WHERE rolname=current_user')).all())
    print('row_counts:', {table: connection.scalar(text('SELECT count(*) FROM ' + table)) for table in ['users', 'courses', 'sessions', 'checkins']})
    for table in ['users', 'courses', 'sessions', 'devices', 'checkins', 'risk_signals']:
        if table in inspect(connection).get_table_names():
            print('columns ' + table + ':', [c['name'] for c in inspect(connection).get_columns(table)])

print('health_with_drifted_database:', health_check())
try:
    with Session(engine) as database_session:
        database_session.scalar(select(Checkin).limit(1))
except Exception as exc:
    print('checkin_model_read_error:', type(exc).__name__, str(exc).split('[SQL:')[0].strip())

schema = app.openapi()
operations = [(method.upper(), path) for path, item in schema['paths'].items() for method in item if method in ['get', 'post', 'put', 'patch', 'delete']]
print('operations:', len(operations), operations)
