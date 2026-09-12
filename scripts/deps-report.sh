#!/usr/bin/env bash
# Report which Python dependencies have a newer release available.
#
# Informational by design. It re-resolves the ranges in api/pyproject.toml to the
# newest versions they allow and prints what differs from the committed lockfiles.
# It never writes a lockfile, never opens a PR, and always exits 0 — deciding what
# to take is the operator's call. Act on it with `make lock-upgrade`.
#
# This exists because Dependabot cannot maintain this lockfile set: it edits
# requirements files in place instead of recompiling, so a shared transitive gets
# resolved separately per file and the result is unsatisfiable (PR #38). The
# resolve here happens in one pass across all three, the same way `make lock` does.
set -euo pipefail
cd "$(dirname "$0")/.."

# Only the pin lines reach stdout; pip's chatter goes to stderr so the capture stays clean.
available="$(./scripts/py.sh '
  pip install --quiet pip-tools 1>&2
  pip-compile --quiet --strip-extras --upgrade -o /tmp/a.txt pyproject.toml 1>&2
  pip-compile --quiet --strip-extras --upgrade --extra dev -o /tmp/b.txt pyproject.toml 1>&2
  pip-compile --quiet --strip-extras --upgrade --extra otel -o /tmp/c.txt pyproject.toml 1>&2
  cat /tmp/a.txt /tmp/b.txt /tmp/c.txt')"

AVAILABLE="$available" python3 - "$@" <<'PY'
import os, re, sys, pathlib

def pins(text):
    out = {}
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s;#]+)", line)
        if m:
            out[m.group(1).lower()] = m.group(2)
    return out

committed = pins("\n".join(
    pathlib.Path("api", f).read_text()
    for f in ("requirements.txt", "requirements-dev.txt", "requirements-otel.txt")
))
latest = pins(os.environ["AVAILABLE"])

rows = sorted(
    (name, committed.get(name, "—"), latest[name])
    for name in latest
    if committed.get(name) != latest[name]
)

md = os.environ.get("GITHUB_STEP_SUMMARY")

if not rows:
    # Still say so. A job that writes nothing when there is nothing looks identical
    # to a job that silently broke.
    msg = "Every Python dependency is already at the newest version its range allows."
    print(msg)
    if md:
        with open(md, "a") as fh:
            fh.write(f"## Python dependencies\n\n{msg}\n")
    sys.exit(0)

width = max(len(r[0]) for r in rows)
print(f"{len(rows)} Python dependenc{'y has' if len(rows) == 1 else 'ies have'} a newer release available:\n")
for name, cur, new in rows:
    print(f"  {name:<{width}}  {cur}  ->  {new}")
print("\nNothing has been changed. Take them with `make lock-upgrade`, review the diff, commit.")

if md:
    with open(md, "a") as fh:
        fh.write(f"## Python dependency updates available ({len(rows)})\n\n")
        fh.write("| package | current | available |\n|---|---|---|\n")
        fh.writelines(f"| `{n}` | {c} | **{v}** |\n" for n, c, v in rows)
        fh.write("\nRun `make lock-upgrade` to take them. Nothing was changed by this job.\n")
PY
