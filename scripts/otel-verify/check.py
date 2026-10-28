"""Inventory what reached Tempo, Prometheus, Loki and Grafana, and check the links.

Runs in a throwaway container on the compose network, because otel-lgtm publishes only
Grafana's port. Standard library only. Prints a JSON report: the inventory, so two runs
can be diffed, plus a "checks" map of name -> {ok, detail}.
"""

import base64
import json
import sys
import time
import urllib.parse
import urllib.request

LGTM = "http://otel-lgtm"
COLLECTOR_METRICS = "http://otel-collector:12345/metrics"
SERVICES = ["alo-web", "alo-api", "alo-worker"]
# The contrib instrumentation the API installs. FastAPI 0.142 added its own, under the
# scope "fastapi", which stands down only when it finds the contrib middleware; a
# span or metric under that scope means both are running, or the wrong one is.
CONTRIB = "opentelemetry.instrumentation."
FASTAPI_NATIVE_SCOPE = "fastapi"
# Grafana's default login, which otel-verify.sh pins for its stack.
GRAFANA_AUTH = "Basic " + base64.b64encode(b"admin:admin").decode()


def get(port: int, path: str, **params: str) -> dict:
    url = f"{LGTM}:{port}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def grafana(path: str):
    req = urllib.request.Request(
        f"{LGTM}:3000/grafana{path}", headers={"Authorization": GRAFANA_AUTH}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def prom(query: str) -> list[dict]:
    return get(9090, "/api/v1/query", query=query)["data"]["result"]


def spans_of(trace: dict) -> list[dict]:
    out = []
    for rs in trace.get("batches") or trace.get("resourceSpans") or []:
        attrs = {a["key"]: a["value"] for a in rs.get("resource", {}).get("attributes", [])}
        svc = attrs.get("service.name", {}).get("stringValue", "?")
        for ss in rs.get("scopeSpans") or rs.get("instrumentationLibrarySpans") or []:
            scope = ss.get("scope") or ss.get("instrumentationLibrary") or {}
            for s in ss.get("spans", []):
                out.append(
                    {
                        "svc": svc,
                        "scope": scope.get("name", ""),
                        "scope_version": scope.get("version", ""),
                        "name": s["name"],
                        "id": s["spanId"],
                        "parent": s.get("parentSpanId", ""),
                        "kind": s.get("kind", ""),
                    }
                )
    return out


def descendants(spans: list[dict], root: dict) -> list[dict]:
    kids: dict[str, list[dict]] = {}
    for s in spans:
        kids.setdefault(s["parent"], []).append(s)
    out, todo = [], [root["id"]]
    while todo:
        for k in kids.get(todo.pop(), []):
            out.append(k)
            todo.append(k["id"])
    return out


def is_server(span: dict) -> bool:
    return span["kind"] in ("SPAN_KIND_SERVER", 2)


report: dict = {"tempo": {}, "prom": {}, "loki": {}, "grafana": {}, "checks": {}}


def check(name: str, ok: bool, detail: str = "") -> None:
    report["checks"][name] = {"ok": bool(ok), "detail": detail}


now = int(time.time())
start = str(now - 3600)

# --- Tempo -----------------------------------------------------------------------------
tags = get(3200, "/api/v2/search/tag/resource.service.name/values")
report["tempo"]["services"] = sorted(v["value"] for v in tags.get("tagValues", []))
traces: dict[str, list[dict]] = {}
report["tempo"]["traces_per_service_search"] = {}
for svc in SERVICES:
    q = f'{{resource.service.name="{svc}"}}'
    found = get(3200, "/api/search", q=q, limit="200", start=start, end=str(now)).get("traces", [])
    report["tempo"]["traces_per_service_search"][svc] = len(found)
    for t in found:
        if t["traceID"] not in traces:
            traces[t["traceID"]] = spans_of(get(3200, f"/api/traces/{t['traceID']}"))
all_spans = [s for ss in traces.values() for s in ss]

inventory: dict[str, set[str]] = {}
for s in all_spans:
    # One DB span per statement; keep only the verb so runs compare cleanly.
    name = s["name"].split()[0] if s["scope"].endswith("sqlalchemy") else s["name"]
    inventory.setdefault(s["svc"], set()).add(f"{s['scope']} :: {name}")
report["tempo"]["inventory"] = {k: sorted(v) for k, v in sorted(inventory.items())}
report["tempo"]["scope_versions"] = sorted(
    {f"{s['svc']} {s['scope']} {s['scope_version']}" for s in all_spans}
)
report["tempo"]["trace_count"] = len(traces)
report["tempo"]["span_count"] = len(all_spans)
report["tempo"]["spans_per_service"] = {
    k: sum(1 for s in all_spans if s["svc"] == k) for k in SERVICES
}
# The collector's own counters. Accepted spans, browser ones included, are there to set
# against what Tempo returned. Refused and failed counts are telemetry lost on the way:
# a batch the receiver turned away, or one the exporter gave up on after its retries.
# Retries that succeed count nowhere, so a store still starting up does not trip this.
LOSS_PREFIXES = (
    "otelcol_receiver_refused_",
    "otelcol_processor_refused_",
    "otelcol_exporter_send_failed_",
    "otelcol_exporter_enqueue_failed_",
)
with urllib.request.urlopen(COLLECTOR_METRICS, timeout=10) as m:
    collector: dict[str, float] = {}
    for line in m.read().decode().splitlines():
        if line.startswith("otelcol_") and not line.startswith("#"):
            name = line.split("{", 1)[0].split(" ", 1)[0]
            collector[name] = collector.get(name, 0.0) + float(line.rsplit(" ", 1)[1])
report["tempo"]["collector_accepted_spans"] = collector.get(
    "otelcol_receiver_accepted_spans_total", 0.0
)
report["collector_loss"] = {
    k: v for k, v in sorted(collector.items()) if k.startswith(LOSS_PREFIXES)
}
lost = {k: v for k, v in report["collector_loss"].items() if v}
check("collector: nothing refused or dropped", not lost, str(lost))

check(
    "tempo: all three services",
    all(s in report["tempo"]["services"] for s in SERVICES),
    str(report["tempo"]["services"]),
)

# The browser's ui.subscribe span is the parent of the API's server span, which is the
# parent of its DB spans: one trace from click to query.
ok, detail = False, ""
for spans in traces.values():
    for root in (s for s in spans if s["svc"] == "alo-web" and s["name"] == "ui.subscribe"):
        below = descendants(spans, root)
        api = [s for s in below if s["svc"] == "alo-api"]
        db = [s for s in api if s["scope"].endswith("sqlalchemy")]
        if api and db:
            ok, detail = True, f"api spans={len(api)} db spans={len(db)}"
check("tempo: ui.subscribe -> alo-api -> sqlalchemy", ok, detail)

for event in ("ui.open_article", "ui.search"):
    check(
        f"tempo: {event} present",
        any(s["svc"] == "alo-web" and s["name"] == event for s in all_spans),
    )

check(
    "tempo: discover web -> api -> httpx in one trace",
    any(
        any(s["svc"] == "alo-api" and s["scope"] == CONTRIB + "httpx" for s in spans)
        and any(s["svc"] == "alo-web" and s["name"] == "POST /api/v1/discover" for s in spans)
        for spans in traces.values()
    ),
)
check(
    "tempo: browser fetch spans",
    any(s["svc"] == "alo-web" and "fetch" in s["scope"] for s in all_spans),
)

ok, detail = False, ""
for spans in traces.values():
    for root in (s for s in spans if s["svc"] == "alo-worker" and s["name"] == "poll_once"):
        below = descendants(spans, root)
        hx = [s for s in below if s["scope"].endswith("httpx")]
        db = [s for s in below if s["scope"].endswith("sqlalchemy")]
        if hx and db:
            ok, detail = True, f"httpx={len(hx)} db={len(db)}"
check("tempo: worker poll_once -> httpx + sqlalchemy", ok, detail)

for lib in ("fastapi", "sqlalchemy", "httpx"):
    check(
        f"tempo: alo-api has {CONTRIB}{lib} spans",
        any(s["svc"] == "alo-api" and s["scope"] == CONTRIB + lib for s in all_spans),
    )

# One server span per request, from the contrib instrumentation. With FastAPI's own
# telemetry running too, it opens the server span and the contrib middleware, seeing
# one already active, demotes its own to INTERNAL: still one server span per request,
# but from the wrong scope, with fastapi.endpoint and similar spans beside it.
api_server = [s for s in all_spans if s["svc"] == "alo-api" and is_server(s)]
server_scopes = sorted({s["scope"] for s in api_server})
check(
    "tempo: alo-api server spans all from the contrib instrumentation",
    server_scopes == [CONTRIB + "fastapi"],
    f"scopes={server_scopes} spans={len(api_server)}",
)
native = sorted({s["name"] for s in all_spans if s["scope"] == FASTAPI_NATIVE_SCOPE})
check("tempo: no spans from FastAPI's own telemetry", not native, str(native[:5]))

# --- Prometheus ------------------------------------------------------------------------
names = get(9090, "/api/v1/label/__name__/values")["data"]
ours = sorted(n for n in names if n.startswith(("alo_", "http_", "db_", "target_info")))
report["prom"]["metric_names"] = ours
age = {}
for n in ours:
    r = prom(f"max(timestamp({n}))")
    age[n] = round(now - float(r[0]["value"][1])) if r else None
report["prom"]["age_seconds"] = age
report["prom"]["services"] = sorted(
    r["metric"].get("service_name", "?") for r in prom("group by (service_name) (target_info)")
)
check(
    "prom: alo-api + alo-worker target_info",
    {"alo-api", "alo-worker"} <= set(report["prom"]["services"]),
    str(report["prom"]["services"]),
)
stale = [n for n, a in age.items() if a is None or a > 300]
check("prom: every metric written in the last 5 min", not stale, str(stale))
for m in (
    "alo_fetch_outcomes",
    "alo_fetch_duration",
    "alo_entries_inserted",
    "alo_worker_lag_seconds",
    "alo_db_bytes",
    "http_server",
):
    check(f"prom: {m}* present", any(n.startswith(m) for n in ours))
# The metric twin of the server-span check. This Prometheus drops the scope name, so
# the instrumentations are told apart by attribute names: the contrib one records the
# old HTTP conventions (http_method; OTEL_SEMCONV_STABILITY_OPT_IN is not set), FastAPI's
# own the stable ones (http_request_method). Both write http_server_active_requests,
# so a series with the stable label means requests are being counted twice.
stable = prom('count by (__name__) ({__name__=~"http_server_.+", http_request_method!=""})')
report["prom"]["http_server_stable_semconv"] = sorted(r["metric"]["__name__"] for r in stable)
check(
    "prom: http_server_* from the contrib instrumentation only",
    not stable,
    str(report["prom"]["http_server_stable_semconv"]),
)

# --- Loki ------------------------------------------------------------------------------
report["loki"]["services"] = sorted(
    get(3100, "/loki/api/v1/label/service_name/values").get("data", [])
)
for svc in ("alo-api", "alo-worker"):
    for label, q in (
        ("lines", f'sum(count_over_time({{service_name="{svc}"}}[1h]))'),
        ("with_trace_id", f'sum(count_over_time({{service_name="{svc}"}} | trace_id != "" [1h]))'),
    ):
        r = get(3100, "/loki/api/v1/query", query=q, time=str(now))["data"]["result"]
        report["loki"][f"{svc} {label}"] = int(float(r[0]["value"][1])) if r else 0
    lines = report["loki"][f"{svc} lines"]
    traced = report["loki"][f"{svc} with_trace_id"]
    check(f"loki: {svc} logs", lines > 0, str(lines))
    check(f"loki: {svc} logs carry trace_id", traced > 0, str(traced))

# --- Grafana ---------------------------------------------------------------------------
g = report["grafana"]
g["version"] = grafana("/api/health").get("version")
g["dashboards"] = sorted(
    f"{d.get('folderTitle', '')}/{d['title']}" for d in grafana("/api/search?type=dash-db")
)
provisioned = {r["uid"]: r["title"] for r in grafana("/api/v1/provisioning/alert-rules")}
g["alert_rules"] = sorted(provisioned)
g["contact_points"] = sorted(
    f"{c['name']}:{c['type']}" for c in grafana("/api/v1/provisioning/contact-points")
)
g["root_receiver"] = grafana("/api/v1/provisioning/policies").get("receiver")
g["datasources"] = sorted(d["type"] for d in grafana("/api/datasources"))
# Each rule has to evaluate against this Prometheus and Loki, not only load.
health = {}
for group in grafana("/api/prometheus/grafana/api/v1/rules")["data"]["groups"]:
    for r in group["rules"]:
        uid = r.get("labels", {}).get("__alert_rule_uid__", r["name"])
        health[uid] = f"{r.get('health')}/{r.get('state')}"
g["rule_health"] = health
check(
    "grafana: 3 alo-reader dashboards",
    sum(d.startswith("alo-reader/") for d in g["dashboards"]) == 3,
    str(g["dashboards"]),
)
check(
    "grafana: 4 alert-floor rules",
    {"alo-worker-lag", "alo-api-5xx", "alo-backup-stale", "alo-disk-free"} <= set(g["alert_rules"]),
    str(g["alert_rules"]),
)
check(
    "grafana: pushover contact point + routing",
    "alo-pushover:pushover" in g["contact_points"] and g["root_receiver"] == "alo-pushover",
    f"{g['contact_points']} root={g['root_receiver']}",
)
# The evaluator names a rule by its uid label when it has one, else by its title.
rule_health = {uid: health.get(uid) or health.get(title) for uid, title in provisioned.items()}
bad = {k: v for k, v in rule_health.items() if not (v and v.startswith("ok"))}
check(
    "grafana: every alert rule evaluates (health ok)",
    bool(rule_health) and not bad,
    str(bad or rule_health),
)

versions = {"grafana": g["version"]}
for name, port, path in (
    ("loki", 3100, "/loki/api/v1/status/buildinfo"),
    ("tempo", 3200, "/api/status/buildinfo"),
    ("prometheus", 9090, "/api/v1/status/buildinfo"),
):
    try:
        b = get(port, path)
        versions[name] = (b.get("data") or b).get("version")
    except Exception as e:  # noqa: BLE001
        versions[name] = f"error: {e}"
report["versions"] = versions

json.dump(report, sys.stdout, indent=1, sort_keys=True)
