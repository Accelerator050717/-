"""Small deterministic v17 helpers; no broker or QuantConnect dependency."""
from datetime import datetime
import hashlib
import json
import math
import statistics


FEATURE_NAMES = (
    "return_5", "return_20", "return_63_skip_20", "return_126_skip_20",
    "volatility_20", "drawdown_63", "log_dollar_volume_shock",
    "log_median_dollar_volume_20",
)


def feature_vector(closes, median_dollar_volume, latest_dollar_volume):
    """127 contemporaneously split-adjusted closes, oldest first.

    Price-return features exclude dividends; native portfolio cash includes them.
    The skip-20 trends deliberately do not chase the latest trading month.
    """
    if len(closes) != 127 or not all(math.isfinite(p) and p > 0 for p in closes):
        raise ValueError("Exactly 127 finite positive prices are required")
    if not all(math.isfinite(p) and p > 0 for p in (median_dollar_volume, latest_dollar_volume)):
        raise ValueError("Dollar-volume observations must be finite and positive")
    daily = [closes[i] / closes[i - 1] - 1 for i in range(len(closes) - 20, len(closes))]
    return [
        closes[-1] / closes[-6] - 1,
        closes[-1] / closes[-21] - 1,
        closes[-21] / closes[-64] - 1,
        closes[-21] / closes[-127] - 1,
        statistics.stdev(daily) * math.sqrt(252),
        closes[-1] / max(closes[-63:]) - 1,
        math.log(latest_dollar_volume / median_dollar_volume),
        math.log(median_dollar_volume),
    ]


def centered_ranks(values):
    """Average rank for exact ties, scaled to [-0.5, 0.5]."""
    if len(values) < 2 or not all(math.isfinite(v) for v in values):
        raise ValueError("At least two finite labels are required")
    ordered = sorted(range(len(values)), key=lambda i: (values[i], i))
    ranks = [0.0] * len(values)
    start = 0
    while start < len(values):
        stop = start + 1
        while stop < len(values) and values[ordered[stop]] == values[ordered[start]]:
            stop += 1
        rank = (start + stop - 1) / 2 / (len(values) - 1) - 0.5
        for k in range(start, stop):
            ranks[ordered[k]] = rank
        start = stop
    return ranks


def eligible_training_rows(rows, deployment_year):
    """Annual freeze uses only labels ending strictly before January 1.

    A label ending on the current January decision date is NOT admitted merely
    because the corresponding bar arrived before that afternoon's fit.
    """
    boundary = datetime(deployment_year, 1, 1)
    return [r for r in rows if r["observed"] < boundary and r["label_end"] < boundary]


def stable_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def continuous_drawdown(values, initial=100000.0):
    peak, deepest = initial, 0.0
    for value in values:
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Equity must be finite and positive")
        peak = max(peak, value)
        deepest = max(deepest, 1 - value / peak)
    return deepest
