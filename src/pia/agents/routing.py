"""Deterministic routing: keyword rules always apply. An AI proposal may add tracks, never remove a match."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class RoutingRules:
    rules: dict[str, tuple[str, ...]]

    @property
    def tracks(self) -> list[str]:
        return sorted(self.rules)

    def match(self, text: str) -> set[str]:
        lowered = text.lower()
        return {track for track, kws in self.rules.items() if any(kw in lowered for kw in kws)}

    @classmethod
    def from_yaml(cls, path: Path) -> RoutingRules:
        data = yaml.safe_load(path.read_text()) or {}
        return cls({name: tuple(spec["keywords"]) for name, spec in data.get("tracks", {}).items()})
