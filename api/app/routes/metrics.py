"""GET /metrics — Prometheus exposition (WP-15, DESIGN.md §1.4).

Internal-only: Caddy restricts this path to private networks (the app itself keeps
it auth-free so a scraper needs no user). Excluded from the OpenAPI schema — it's an
ops surface, not part of the typed client contract. Combines live gauges (worker
lag, table/DB sizes) with the worker-recorded counters (fetch outcomes, per-host
403/429).
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import httpmetrics
from app.db import get_session
from app.metrics import CONTENT_TYPE, Family, label_str, render
from app.store import metrics as metrics_store

router = APIRouter(tags=["ops"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/metrics", include_in_schema=False)
async def metrics(session: Session) -> PlainTextResponse:
    families: list[Family] = []

    lag = Family("alo_worker_lag_seconds", "Age of the oldest due, unclaimed feed.", "gauge")
    lag.add(await metrics_store.worker_lag_seconds(session))
    families.append(lag)

    outcomes = Family(metrics_store.FETCH_OUTCOMES, "Feed fetches by outcome class.", "counter")
    hosts = Family(metrics_store.FETCH_HOST_RESPONSES, "Per-host 403/429 responses.", "counter")
    by_name = {outcomes.name: outcomes, hosts.name: hosts}
    for c in await metrics_store.all_counters(session):
        fam = by_name.get(c.name)
        if fam is not None:
            fam.add(c.value, c.label)
    families.append(outcomes)
    families.append(hosts)

    sizes = Family("alo_table_bytes", "Total on-disk size per table.", "gauge")
    counts = Family("alo_table_rows", "Approximate row count per table.", "gauge")
    for ts in await metrics_store.table_sizes(session):
        label = label_str([("table", ts.table)])
        sizes.add(ts.bytes, label)
        counts.add(ts.rows, label)
    families.append(sizes)
    families.append(counts)

    db = Family("alo_db_bytes", "Total database size.", "gauge")
    db.add(await metrics_store.db_size_bytes(session))
    families.append(db)

    # In-process HTTP RED counters (per replica).
    reqs = Family("alo_http_requests_total", "HTTP requests by method and status.", "counter")
    for method, status, count in httpmetrics.snapshot_requests():
        reqs.add(count, label_str([("method", method), ("status", str(status))]))
    families.append(reqs)

    sum_s, count = httpmetrics.duration_totals()
    dur_sum = Family("alo_http_request_duration_seconds_sum", "Total request duration.", "counter")
    dur_sum.add(sum_s)
    dur_count = Family(
        "alo_http_request_duration_seconds_count", "Total requests timed.", "counter"
    )
    dur_count.add(count)
    families.append(dur_sum)
    families.append(dur_count)

    return PlainTextResponse(render(families), media_type=CONTENT_TYPE)
