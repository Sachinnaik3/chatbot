"""In-process metrics: counters and latency samples, exported in Prometheus text format.

In production, scrape /metrics from inside the cluster (the endpoint is blocked at the
ingress by network policy). Labels must never contain user text or IDs of people.
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque

Labels = tuple[tuple[str, str], ...]
MAX_SAMPLES = 10_000


def _labels(labels: dict[str, str] | None) -> Labels:
    return tuple(sorted((labels or {}).items()))


def _fmt(labels: Labels) -> str:
    return "{" + ",".join(f'{k}="{v}"' for k, v in labels) + "}" if labels else ""


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[idx]


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: defaultdict[tuple[str, Labels], float] = defaultdict(float)
        self._samples: defaultdict[tuple[str, Labels], deque[float]] = defaultdict(lambda: deque(maxlen=MAX_SAMPLES))

    def inc(self, name: str, labels: dict[str, str] | None = None, value: float = 1.0) -> None:
        with self._lock:
            self._counters[(name, _labels(labels))] += value

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            self._samples[(name, _labels(labels))].append(value)

    def counter(self, name: str, labels: dict[str, str] | None = None) -> float:
        return self._counters.get((name, _labels(labels)), 0.0)

    def samples(self, name: str) -> list[float]:
        with self._lock:
            return [v for (n, _), vals in self._samples.items() if n == name for v in vals]

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            for (name, labels), value in sorted(self._counters.items()):
                lines.append(f"{name}{_fmt(labels)} {value}")
            for (name, labels), vals in sorted(self._samples.items()):
                data = list(vals)
                for q in (0.5, 0.95, 0.99):
                    ql = _fmt(tuple(sorted((*labels, ("quantile", str(q))))))
                    lines.append(f"{name}{ql} {percentile(data, q):.6f}")
                lines.append(f"{name}_count{_fmt(labels)} {len(data)}")
        return "\n".join(lines) + "\n"
