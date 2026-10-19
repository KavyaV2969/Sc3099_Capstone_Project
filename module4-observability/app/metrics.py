"""
Prometheus query helpers for the "System Metrics" page.

Query shapes come from docs/recommended_design/INTEGRATION-GUIDE.md
("Module 4: Dashboard -> Prometheus"). Metric *names* are only a convention
until your Module 2 teammate's `/metrics` endpoint actually exists - see the
comment block in config.py if a panel here shows "no data".
"""
from __future__ import annotations

import requests

from config import (
    PROMETHEUS_URL,
    METRIC_HTTP_DURATION_BUCKET,
    METRIC_HTTP_REQUESTS_TOTAL,
    METRIC_CHECKIN_ATTEMPTS_TOTAL,
    METRIC_CHECKIN_SUCCESS_TOTAL,
)

PROM_TIMEOUT = 5


def query_prometheus(promql: str) -> dict | None:
    try:
        resp = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query", params={"query": promql}, timeout=PROM_TIMEOUT
        )
        resp.raise_for_status()
        payload = resp.json()
        return payload if payload.get("status") == "success" else None
    except requests.RequestException:
        return None


def query_range(promql: str, start: float, end: float, step: str = "30s") -> dict | None:
    try:
        resp = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query_range",
            params={"query": promql, "start": start, "end": end, "step": step},
            timeout=PROM_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
        return payload if payload.get("status") == "success" else None
    except requests.RequestException:
        return None


def _scalar(promql: str) -> float | None:
    data = query_prometheus(promql)
    try:
        return float(data["data"]["result"][0]["value"][1])
    except (TypeError, KeyError, IndexError, ValueError):
        return None


def prometheus_reachable() -> bool:
    return query_prometheus("up") is not None


def targets_up() -> dict[str, list[tuple[str, bool]]]:
    """job -> [(instance, is_up), ...] using the built-in `up` metric."""
    data = query_prometheus("up")
    out: dict[str, list[tuple[str, bool]]] = {}
    try:
        for r in data["data"]["result"]:
            job = r["metric"].get("job", "unknown")
            instance = r["metric"].get("instance", "")
            out.setdefault(job, []).append((instance, r["value"][1] == "1"))
    except (TypeError, KeyError):
        pass
    return out


def get_latency_p95_ms(job: str) -> float | None:
    q = (
        f'histogram_quantile(0.95, sum(rate('
        f'{METRIC_HTTP_DURATION_BUCKET}{{job="{job}"}}[5m])) by (le))'
    )
    v = _scalar(q)
    return v * 1000 if v is not None else None


def get_request_rate(job: str) -> float | None:
    return _scalar(f'sum(rate({METRIC_HTTP_REQUESTS_TOTAL}{{job="{job}"}}[5m]))')


def get_error_rate_pct(job: str) -> float | None:
    total = _scalar(f'sum(rate({METRIC_HTTP_REQUESTS_TOTAL}{{job="{job}"}}[5m]))')
    if not total:
        return None
    err = _scalar(f'sum(rate({METRIC_HTTP_REQUESTS_TOTAL}{{job="{job}", status=~"5.."}}[5m])) OR on() vector(0)')
    return (err or 0.0) / total * 100


def get_checkin_success_rate_pct() -> float | None:
    q = (
        f"sum(rate({METRIC_CHECKIN_SUCCESS_TOTAL}[5m])) / "
        f"sum(rate({METRIC_CHECKIN_ATTEMPTS_TOTAL}[5m])) * 100"
    )
    return _scalar(q)


def get_request_rate_series(job: str, minutes: int = 30):
    """Returns (timestamps, values) for a small request-rate sparkline."""
    import time

    end = time.time()
    start = end - minutes * 60
    data = query_range(
        f'sum(rate({METRIC_HTTP_REQUESTS_TOTAL}{{job="{job}"}}[5m]))', start, end, "30s"
    )
    try:
        values = data["data"]["result"][0]["values"]
    except (TypeError, KeyError, IndexError):
        return [], []
    ts = [v[0] for v in values]
    ys = [float(v[1]) for v in values]
    return ts, ys
