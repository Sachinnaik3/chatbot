"""Metric helpers. Each returns a value in [0, 1] unless stated otherwise."""

from __future__ import annotations


def recall_at_k(retrieved: list[str], expected: set[str], k: int) -> float:
    if not expected:
        raise ValueError("recall is undefined without expected items")
    return len(set(retrieved[:k]) & expected) / len(expected)


def rate(hits: int, total: int) -> float:
    return hits / total if total else 1.0
