"""Summarise an otel-verify run, or diff two of them.

    python3 report.py summary RUN_DIR          exit 1 if anything failed
    python3 report.py compare BASE_DIR RUN_DIR  what one run has that the other lacks

A run fails on any failed check, any browser step that did not finish, any OTLP
export the collector refused, and any instrumentor that will not run (see pkgs.py).
"""

import json
import sys
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def summary(run: Path) -> int:
    failed = 0
    for name, c in load(run / "report.json")["checks"].items():
        failed += not c["ok"]
        detail = f"   [{c['detail']}]" if c["detail"] else ""
        print(f"{'PASS' if c['ok'] else 'FAIL'} {name}{detail}")
    for f in sorted(run.glob("drive-*.json")):
        d = load(f)
        bad_steps = [s for s in d["steps"] if s[1] != "ok"]
        bad_otlp = [s for s in d["otlp"] if not 200 <= s < 300]
        ok = bool(d["otlp"]) and not bad_steps and not bad_otlp
        failed += not ok
        print(
            f"{'PASS' if ok else 'FAIL'} browser {d['phase']}: steps={d['steps']} "
            f"otlp posts={len(d['otlp'])} non-2xx={bad_otlp} "
            f"console errors={len(d['consoleErrors'])}"
        )
    for f in sorted(run.glob("pkgs-*.json")):
        p = load(f)
        svc = f.stem.removeprefix("pkgs-")
        conflicts = {k: v for k, v in p["conflicts"].items() if v}
        ok = not conflicts and not p["pip_check"]
        failed += not ok
        print(
            f"{'PASS' if ok else 'FAIL'} {svc}: every instrumentor will run"
            + (f"   [conflicts={conflicts} pip check={p['pip_check']!r}]" if not ok else "")
        )
    print(f"\n{failed} failed" if failed else "\nall passed")
    return 1 if failed else 0


def compare(base_dir: Path, run_dir: Path) -> int:
    a, b = load(base_dir / "report.json"), load(run_dir / "report.json")
    an, bn = base_dir.name, run_dir.name

    def diff(label: str, x: list, y: list) -> None:
        x, y = set(x), set(y)
        if x - y:
            print(f"  only in {an}, {label}: {sorted(x - y)}")
        if y - x:
            print(f"  only in {bn}, {label}: {sorted(y - x)}")

    print(f"{an} -> {bn}")
    inv_a, inv_b = a["tempo"]["inventory"], b["tempo"]["inventory"]
    for svc in sorted(set(inv_a) | set(inv_b)):
        diff(f"spans[{svc}]", inv_a.get(svc, []), inv_b.get(svc, []))
    diff("metrics", a["prom"]["metric_names"], b["prom"]["metric_names"])
    for store in ("tempo", "prom", "loki"):
        diff(f"{store} services", a[store]["services"], b[store]["services"])
    spans_a, spans_b = a["tempo"]["spans_per_service"], b["tempo"]["spans_per_service"]
    for k in sorted(spans_a):
        print(f"  spans {k}: {spans_a[k]} -> {spans_b.get(k)}")
    for k in sorted(k for k in a["loki"] if k != "services"):
        print(f"  loki {k}: {a['loki'][k]} -> {b['loki'].get(k)}")
    for k in sorted(set(a["versions"]) | set(b["versions"])):
        if a["versions"].get(k) != b["versions"].get(k):
            print(f"  {k}: {a['versions'].get(k)} -> {b['versions'].get(k)}")
    for svc in ("api", "worker"):
        pa, pb = run_pkgs(base_dir, svc), run_pkgs(run_dir, svc)
        for pkg in sorted(set(pa) | set(pb)):
            if pa.get(pkg) != pb.get(pkg):
                print(f"  {svc} {pkg}: {pa.get(pkg)} -> {pb.get(pkg)}")
    return 0


def run_pkgs(run: Path, svc: str) -> dict:
    f = run / f"pkgs-{svc}.json"
    if not f.exists():
        return {}
    p = load(f)
    return {**p["otel"], **{k: v for k, v in p["libs"].items() if v}}


if __name__ == "__main__":
    mode, *dirs = sys.argv[1:]
    sys.exit(summary(Path(dirs[0])) if mode == "summary" else compare(Path(dirs[0]), Path(dirs[1])))
