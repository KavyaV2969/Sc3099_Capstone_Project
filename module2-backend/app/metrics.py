"""Bounded-cardinality backend metrics and per-request correlation context."""
from contextvars import ContextVar
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

request_id = ContextVar("request_id", default="")
traceparent = ContextVar("traceparent", default="")
registry = CollectorRegistry()
request_duration = Histogram("http_request_duration_seconds", "HTTP response duration", ["method", "route", "status"], registry=registry)
request_errors = Counter("http_request_errors_total", "HTTP failures", ["status"], registry=registry)
checkin_attempts = Counter("checkin_attempts_total", "Student check-in submissions", registry=registry)
checkin_success = Counter("checkin_success_total", "Approved check-ins at submission", registry=registry)
checkin_outcomes = Counter("checkin_outcomes_total", "Stored check-in outcomes", ["status"], registry=registry)
dependency_duration = Histogram("backend_dependency_duration_seconds", "Dependency calls", ["operation", "category"], registry=registry)
retention_runs = Counter("retention_runs_total", "Retention runs", ["result"], registry=registry)
retention_last_success = Gauge("retention_last_success_timestamp_seconds", "Last successful cleanup", registry=registry)
retention_records = Counter("retention_records_total", "Cleaned records", ["kind"], registry=registry)
