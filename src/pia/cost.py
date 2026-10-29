"""Token and cost accounting per scope (a review, a user, or a job). Enforces a hard budget."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


class BudgetExceeded(Exception):
    pass


def load_prices(path: Path) -> dict[str, dict[str, float]]:
    data: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    return data.get("pricing_usd_per_mtok", {})


def estimate_usd(prices: dict[str, dict[str, float]], model: str, tokens_in: int, tokens_out: int) -> float:
    if model not in prices:
        raise ValueError(f"no price configured for model {model}; add it to configs/models.yaml")
    p = prices[model]
    return (tokens_in * p["input"] + tokens_out * p["output"]) / 1_000_000


class CostTracker:
    def __init__(self, prices: dict[str, dict[str, float]], token_budget_per_scope: int) -> None:
        self._prices = prices
        self._budget = token_budget_per_scope
        self._tokens: defaultdict[str, int] = defaultdict(int)
        self._usd: defaultdict[str, float] = defaultdict(float)

    def ensure_budget(self, scope: str) -> None:
        if self._tokens[scope] >= self._budget:
            raise BudgetExceeded(scope)

    def record(self, scope: str, model: str, tokens_in: int, tokens_out: int) -> None:
        self._tokens[scope] += tokens_in + tokens_out
        self._usd[scope] += estimate_usd(self._prices, model, tokens_in, tokens_out)

    def usd(self, scope: str) -> float:
        return round(self._usd[scope], 6)

    def tokens(self, scope: str) -> int:
        return self._tokens[scope]
