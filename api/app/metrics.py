"""Prometheus text-exposition helpers (WP-15, DESIGN.md §1.4).

Hand-rolled (no prometheus_client dependency): a couple of pure formatters used by
the /metrics route and the worker's counter recording. Escaping follows the
Prometheus text format spec for label values (backslash, double-quote, newline).
"""

from dataclasses import dataclass, field

_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def label_str(pairs: list[tuple[str, str]]) -> str:
    """Format ``[(k, v), …]`` as Prometheus label content, e.g. ``k="v",…`` (no braces)."""
    return ",".join(f'{k}="{escape_label_value(v)}"' for k, v in pairs)


@dataclass
class Family:
    """One metric family: a name, HELP text, TYPE, and its (label, value) samples."""

    name: str
    help: str
    type: str  # "gauge" | "counter"
    samples: list[tuple[str, float]] = field(default_factory=list)  # (label content, value)

    def add(self, value: float, label: str = "") -> None:
        self.samples.append((label, value))


def render(families: list[Family]) -> str:
    """Render metric families to the Prometheus text exposition format."""
    lines: list[str] = []
    for fam in families:
        lines.append(f"# HELP {fam.name} {fam.help}")
        lines.append(f"# TYPE {fam.name} {fam.type}")
        for label, value in fam.samples:
            series = f"{fam.name}{{{label}}}" if label else fam.name
            lines.append(f"{series} {_num(value)}")
    return "\n".join(lines) + "\n"


def _num(value: float) -> str:
    # Emit whole numbers without a trailing ".0" (matches common exporters).
    return str(int(value)) if float(value).is_integer() else repr(float(value))


CONTENT_TYPE = _CONTENT_TYPE
