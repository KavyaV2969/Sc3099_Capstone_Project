"""Expose the unmodified backend over HTTP with a migrated disposable SQLite DB.

Redis keys are namespaced per audit run to avoid affecting existing rate counters.
"""
import os
import sys
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[2]
backend = root / 'module2-backend'
database = root / 'tmp/backend-audit/public-http.sqlite3'
os.environ['DATABASE_URL'] = 'sqlite:///' + database.as_posix()
os.environ['SECRET_KEY'] = secrets.token_urlsafe(48)
os.environ['RETENTION_CLEANUP_ENABLED'] = 'false'
sys.path.insert(0, str(backend))

from alembic import command
from alembic.config import Config
config = Config(str(backend / 'alembic.ini'))
config.set_main_option('script_location', str(backend / 'alembic'))
command.upgrade(config, 'head')

from app import rate_limit
actual = rate_limit.get_redis_client()
namespace = 'audit-' + secrets.token_hex(8) + ':'

class NamespacedRedis:
    def ping(self): return actual.ping()
    def eval(self, script, numkeys, *args):
        keys = [namespace + str(k) for k in args[:numkeys]]
        return actual.eval(script, numkeys, *keys, *args[numkeys:])
    def get(self, key): return actual.get(namespace + key)
    def setex(self, key, ttl, value): return actual.setex(namespace + key, ttl, value)

rate_limit.get_redis_client = lambda: NamespacedRedis()
import uvicorn
from app.main import app
uvicorn.run(app, host='127.0.0.1', port=18000, log_level='warning', access_log=False)
