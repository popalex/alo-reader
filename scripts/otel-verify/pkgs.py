"""Print the installed OpenTelemetry packages and whether each instrumentor will run.

Runs inside the api and worker containers (`python - < pkgs.py`). An instrumentor whose
library is outside its supported range does not fail: it skips instrumenting and logs
nothing, so its spans just stop arriving. get_dependency_conflicts() is what it checks
before deciding, so a non-None result here means that instrumentor is off.
"""

import importlib.metadata as md
import json
import subprocess

from opentelemetry.instrumentation.dependencies import get_dependency_conflicts
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

installed = {d.metadata["Name"].lower(): d.version for d in md.distributions()}
instrumentors = (
    FastAPIInstrumentor,
    HTTPXClientInstrumentor,
    LoggingInstrumentor,
    SQLAlchemyInstrumentor,
)
libs = ("fastapi", "starlette", "sqlalchemy", "httpx", "grpcio", "protobuf")
conflicts = {
    i.__name__: get_dependency_conflicts(i().instrumentation_dependencies()) for i in instrumentors
}
pip_check = subprocess.run(["pip", "check"], capture_output=True, text=True)
report = {
    "otel": {k: v for k, v in sorted(installed.items()) if k.startswith("opentelemetry")},
    "libs": {k: installed.get(k) for k in libs},
    "conflicts": {k: str(v) if v is not None else None for k, v in conflicts.items()},
    # Empty means it passed. A failure keeps all its output, and its exit code in case
    # it printed nothing, so report.py cannot mistake it for a pass.
    "pip_check": (
        f"exit {pip_check.returncode}: {(pip_check.stdout + pip_check.stderr).strip()}"
        if pip_check.returncode
        else ""
    ),
}
print(json.dumps(report, indent=1))
