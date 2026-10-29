from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class SqlAllowlist:
    tables: dict[str, tuple[str, ...]]

    @property
    def table_names(self) -> frozenset[str]:
        return frozenset(self.tables)

    @property
    def columns(self) -> frozenset[str]:
        return frozenset(c for cols in self.tables.values() for c in cols)

    def schema_text(self) -> str:
        return "\n".join(f"{t}({', '.join(cols)})" for t, cols in sorted(self.tables.items()))

    @classmethod
    def from_yaml(cls, path: Path) -> SqlAllowlist:
        data = yaml.safe_load(path.read_text()) or {}
        return cls({t: tuple(cols) for t, cols in data.get("tables", {}).items()})
