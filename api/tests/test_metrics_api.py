"""/metrics Prometheus exposition (WP-15, DESIGN.md §1.4).

Covers the renderer/escaping (unit) and the endpoint end-to-end against real
Postgres: worker lag reflects a due feed, worker-recorded counters surface, table
size/row gauges appear, and the endpoint needs no auth (Caddy gates it, not a user).
"""

import httpx
from sqlalchemy import text

from app import db as app_db
from app.metrics import Family, escape_label_value, label_str, render
from app.store import metrics as metrics_store
from tests import factories

METRICS = "/api/v1/metrics"


# ── Renderer (pure) ──────────────────────────────────────────────────────────


def test_label_escaping() -> None:
    assert escape_label_value('a"b\\c\nd') == 'a\\"b\\\\c\\nd'
    assert label_str([("host", "ex.com"), ("code", "429")]) == 'host="ex.com",code="429"'


def test_render_format() -> None:
    fam = Family("alo_thing_total", "A thing.", "counter")
    fam.add(3, 'class="x"')
    fam.add(2.5)
    out = render([fam])
    assert "# HELP alo_thing_total A thing." in out
    assert "# TYPE alo_thing_total counter" in out
    assert 'alo_thing_total{class="x"} 3' in out
    assert "alo_thing_total 2.5" in out
    assert out.endswith("\n")


# ── Endpoint ─────────────────────────────────────────────────────────────────


async def test_metrics_needs_no_auth_and_is_text(api_client: httpx.AsyncClient) -> None:
    resp = await api_client.get(METRICS)  # no Authorization header
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    assert "alo_worker_lag_seconds" in body
    assert "alo_db_bytes" in body
    assert 'alo_table_bytes{table="entries"}' in body
    assert 'alo_table_rows{table="feeds"}' in body


async def test_worker_lag_reflects_due_feed(api_client: httpx.AsyncClient) -> None:
    sf = app_db.get_sessionmaker()
    async with sf() as s, s.begin():
        feed = await factories.make_feed(s)
        # Due 1000s ago, unclaimed → lag ≈ 1000s.
        await s.execute(
            text(
                "UPDATE feeds SET next_check_at = now() - interval '1000 seconds', "
                "claimed_until = 'epoch' WHERE id = :id"
            ),
            {"id": feed.id},
        )
    async with sf() as s:
        lag = await metrics_store.worker_lag_seconds(s)
    assert lag >= 1000.0

    body = (await api_client.get(METRICS)).text
    line = next(line for line in body.splitlines() if line.startswith("alo_worker_lag_seconds "))
    assert float(line.split()[1]) >= 1000.0


async def test_fetch_counters_surface(api_client: httpx.AsyncClient) -> None:
    sf = app_db.get_sessionmaker()
    async with sf() as s, s.begin():
        await metrics_store.record_fetch(s, host="a.example", outcome="new_body", http_status=200)
        await metrics_store.record_fetch(
            s, host="a.example", outcome="not_modified", http_status=304
        )
        await metrics_store.record_fetch(s, host="b.example", outcome="http_error", http_status=429)
        await metrics_store.record_fetch(s, host="b.example", outcome="http_error", http_status=429)

    body = (await api_client.get(METRICS)).text
    assert 'alo_fetch_outcomes_total{class="new_body"} 1' in body
    assert 'alo_fetch_outcomes_total{class="not_modified"} 1' in body
    assert 'alo_fetch_outcomes_total{class="http_error"} 2' in body
    # Per-host 403/429 only (200/304 are not host-status counters).
    assert 'alo_fetch_host_responses_total{host="b.example",code="429"} 2' in body
    assert 'host="a.example"' not in body  # a.example never 403/429
