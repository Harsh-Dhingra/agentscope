"""Two-window distribution checks with a reproducible permutation test.

This tests exchangeable reference/current observations, not concept drift or causality.
"""

import bisect
import random
import statistics
import time
import uuid
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class MetricWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9 _.-]+$")
    kind: Literal["input", "output", "quality", "retrieval", "operational"]
    unit: str = Field(default="value", max_length=20, pattern=r"^[A-Za-z0-9 _%./-]+$")
    reference: list[float] = Field(min_length=30, max_length=256)
    current: list[float] = Field(min_length=30, max_length=256)


class DriftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    label: str = Field(default="Custom window comparison", max_length=80)
    metrics: list[MetricWindow] = Field(min_length=1, max_length=6)
    alpha: float = Field(default=0.05, ge=0.001, le=0.2)
    min_effect: float = Field(default=0.2, ge=0, le=1)


def ks_distance(x, y):
    x, y = sorted(x), sorted(y)
    return max(
        abs(bisect.bisect_right(x, v) / len(x) - bisect.bisect_right(y, v) / len(y))
        for v in set(x + y)
    )


def permutation_p(x, y, observed, permutations=399):
    rng = random.Random(173)
    pooled = list(x) + list(y)
    n = len(x)
    extreme = 0
    for _ in range(permutations):
        rng.shuffle(pooled)
        if ks_distance(pooled[:n], pooled[n:]) >= observed - 1e-12:
            extreme += 1
    return (extreme + 1) / (permutations + 1)


def histogram(x, y):
    lo = min(x + y)
    hi = max(x + y)
    if hi == lo:
        lo -= 0.5
        hi += 0.5
    width = (hi - lo) / 12

    def counts(values):
        out = [0] * 12
        for v in values:
            out[min(11, max(0, int((v - lo) / width)))] += 1
        return [count / len(values) for count in out]

    return {
        "edges": [lo + i * width for i in range(13)],
        "reference": counts(x),
        "current": counts(y),
    }


def analyze(request: DriftRequest, store, source="custom"):
    rows = []
    for metric in request.metrics:
        stat = ks_distance(metric.reference, metric.current)
        p = permutation_p(metric.reference, metric.current, stat)
        adjusted = min(1, p * len(request.metrics))
        rows.append(
            {
                "name": metric.name,
                "kind": metric.kind,
                "unit": metric.unit,
                "n_reference": len(metric.reference),
                "n_current": len(metric.current),
                "reference_mean": statistics.mean(metric.reference),
                "current_mean": statistics.mean(metric.current),
                "ks_distance": stat,
                "p_value": p,
                "adjusted_p_value": adjusted,
                "shift_detected": adjusted < request.alpha
                and stat >= request.min_effect,
                "histogram": histogram(metric.reference, metric.current),
            }
        )
    report = {
        "id": str(uuid.uuid4()),
        "created_at": time.time(),
        "label": request.label,
        "source": source,
        "method": "Two-sample KS distance; 399 label permutations; Bonferroni correction across submitted metrics",
        "alpha": request.alpha,
        "min_effect": request.min_effect,
        "rows": rows,
        "alert_count": sum(r["shift_detected"] for r in rows),
        "limitations": "Assumes exchangeable observations. Correlated time series need block-aware methods. A distribution shift is not proof of quality degradation or its cause. Synthetic scenarios do not calibrate production thresholds.",
    }
    store.put("drift_reports", report)
    return report


def demo_request(scenario):
    rng = random.Random(91)
    settings = [
        ("Input length", "input", "tokens", 120, 15),
        ("Output length", "output", "tokens", 90, 12),
        ("Reviewed correctness", "quality", "score", 0.88, 0.04),
        ("Knowledge age", "retrieval", "days", 8, 2),
        ("Inference latency", "operational", "ms", 350, 30),
    ]
    metrics = []
    for name, kind, unit, mean, sd in settings:
        ref = [max(0, rng.gauss(mean, sd)) for _ in range(64)]
        changed = mean
        if scenario == "latency_spike" and kind == "operational":
            changed = 620
        if scenario == "quality_regression" and kind == "quality":
            changed = 0.60
        if scenario == "knowledge_aging" and kind == "retrieval":
            changed = 40
        current = [max(0, rng.gauss(changed, sd)) for _ in range(64)]
        metrics.append(
            MetricWindow(
                name=name, kind=kind, unit=unit, reference=ref, current=current
            )
        )
    return DriftRequest(label=scenario.replace("_", " ").title(), metrics=metrics)
