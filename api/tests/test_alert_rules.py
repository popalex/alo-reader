"""The provisioned alert floor has to keep pointing at metrics that exist.

An alert rule is the one piece of config that fails silently in the direction you
care about: rename a gauge and the query returns nothing, which Grafana shows as
NoData, which two of the four rules treat as healthy. Nothing in the stack would
tell you the alarm had been disarmed. So the promql is checked against the metrics
this repo actually produces, and the rule shapes are checked against the fields
that decide whether a rule can fire at all.

Two producers, because two of them are not Python: telemetry.py creates the app's
instruments, and deploy/backup.sh writes the backup sidecar's node_exporter
textfile metrics. Both are parsed from source, so renaming a metric in either one
without updating the rule fails here.

Structure only. Thresholds are an operator's call, documented in docs/ALERTS.md.
"""

import os
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

RULES_PATH = "deploy/observability/alerting/alo-floor.yml"
TELEMETRY_PATH = "api/app/telemetry.py"
BACKUP_SCRIPT_PATH = "deploy/backup.sh"

# The suffixes the OTel Prometheus exporter appends. Stripped before a name is
# matched against the instrument it came from.
_SUFFIXES = ("_total", "_bucket", "_count", "_sum", "_seconds", "_bytes", "_milliseconds")


def _repo_file(relative: str) -> Path:
    root = os.getenv("ALO_REPO_ROOT")
    candidates = [Path(root) / relative] if root else []
    candidates.append(Path(__file__).resolve().parents[2] / relative)
    for path in candidates:
        if path.is_file():
            return path
    pytest.fail(f"{relative} not found; looked in {[str(c) for c in candidates]}")


def _rules() -> list[dict[str, Any]]:
    groups = yaml.safe_load(_repo_file(RULES_PATH).read_text(encoding="utf-8"))["groups"]
    return [rule for group in groups for rule in group["rules"]]


def _telemetry_metric_names() -> set[str]:
    """Instrument names from telemetry.py, in the form Prometheus stores them."""
    source = _repo_file(TELEMETRY_PATH).read_text(encoding="utf-8")
    names = set(re.findall(r'"(alo\.[a-z_.]+)"', source))
    assert names, "no alo.* instruments found in telemetry.py; the regex has rotted"
    return {name.replace(".", "_") for name in names}


def _backup_metric_names() -> set[str]:
    """Metric names the backup sidecar writes, read out of its heredoc.

    Already in Prometheus form — the textfile collector passes names through
    untouched, which is the point of using it.
    """
    source = _repo_file(BACKUP_SCRIPT_PATH).read_text(encoding="utf-8")
    names = set(re.findall(r"^(alo_[a-z_]+) ", source, re.MULTILINE))
    assert names, f"no alo_* metrics found in {BACKUP_SCRIPT_PATH}; the regex has rotted"
    return names


def _exported_metric_names() -> set[str]:
    return _telemetry_metric_names() | _backup_metric_names()


def _strip_suffixes(name: str) -> set[str]:
    """A metric name plus every prefix of it the exporter could have extended."""
    variants = {name}
    changed = True
    while changed:
        changed = False
        for variant in list(variants):
            for suffix in _SUFFIXES:
                if variant.endswith(suffix) and variant != suffix:
                    trimmed = variant[: -len(suffix)]
                    if trimmed not in variants:
                        variants.add(trimmed)
                        changed = True
    return variants


def test_app_metrics_in_alerts_are_actually_exported() -> None:
    exported = _exported_metric_names()
    for rule in _rules():
        for query in rule["data"]:
            for used in re.findall(r"\balo_[a-z_]+", str(query["model"].get("expr", ""))):
                assert _strip_suffixes(used) & exported, (
                    f"{rule['title']!r} queries {used}, which nothing in "
                    f"{TELEMETRY_PATH} or {BACKUP_SCRIPT_PATH} produces. "
                    f"Exported: {sorted(exported)}"
                )


def test_every_rule_can_fire() -> None:
    """The fields whose absence turns a rule into decoration."""
    seen_uids = set()
    for rule in _rules():
        title = rule["title"]
        assert rule["uid"] not in seen_uids, f"duplicate uid on {title!r}"
        seen_uids.add(rule["uid"])
        assert not rule.get("isPaused"), f"{title!r} is paused"
        refs = {query["refId"] for query in rule["data"]}
        assert rule["condition"] in refs, f"{title!r} conditions on a missing refId"
        assert rule["for"], f"{title!r} has no pending period"
        # Both states are deliberate per rule (see docs/ALERTS.md); what matters is
        # that neither was left to Grafana's default.
        assert rule["noDataState"] in {"OK", "Alerting", "NoData"}
        assert rule["execErrState"] in {"OK", "Alerting", "Error"}
        assert rule["annotations"]["summary"]
        assert "docs/ALERTS.md" in rule["annotations"]["description"], (
            f"{title!r} does not point at its runbook"
        )


def test_queries_target_the_provisioned_datasource() -> None:
    for rule in _rules():
        for query in rule["data"]:
            uid = query["datasourceUid"]
            assert uid in {"prometheus", "__expr__"}, (
                f"{rule['title']!r} queries datasource {uid!r}, which the otel-lgtm "
                "stack does not provision"
            )


def test_the_floor_is_the_four_documented_alerts() -> None:
    assert {rule["uid"] for rule in _rules()} == {
        "alo-worker-lag",
        "alo-api-5xx",
        "alo-backup-stale",
        "alo-disk-free",
    }


def test_the_backup_metrics_the_sidecar_writes_are_the_ones_documented() -> None:
    """The sidecar's four gauges are an interface: the rule and the runbook use them."""
    assert _backup_metric_names() == {
        "alo_backup_last_success_timestamp_seconds",
        "alo_backup_last_success_bytes",
        "alo_backup_last_attempt_timestamp_seconds",
        "alo_backup_last_attempt_success",
    }
