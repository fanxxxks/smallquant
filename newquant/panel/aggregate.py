"""Stock scores → sleeve scores, with the coverage term the review asked for.

The equity sleeve is an ETF, but the panel predicts stocks. The bridge is the index weight
file, and it has three properties that decide how the score may be reported:

* the weights are monthly snapshots, so at a month-end signal date the newest snapshot whose
  ``available_date`` has passed is the **previous** month's — E1 is one month stale on
  membership by construction, not by bug;
* a member can be missing a prediction (newly listed, halted, outside the fitted universe),
  so any weighted mean over *predicted* members silently renormalises to the part of the
  basket the model happens to cover;
* therefore coverage is reported next to every score, and a sleeve score never appears
  alone. `coverage == 0.41` means 41 % of the basket by weight was predictable that month,
  and a claim about "the sleeve" would be a claim about less than half of it.

`deviation_share` answers the objection that a panel model cannot say anything a sleeve-level
model could not: the sleeve score is a weighted mean, so it contains a common component that
every broad ETF shares and a deviation component that only the sleeve's own composition
produces. If all of the score's month-to-month variance is common, the panel is doing nothing
that a single equity index fund would not do, and the share says so numerically.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from .source import EQUITY_BRIDGE, index_weights

MIN_COVERAGE_TO_REPORT = 0.30


def sleeve_table(
    predictions: pd.DataFrame,
    con: duckdb.DuckDBPyConnection,
    dates: list[str],
    *,
    prediction_column: str = "score",
    bridge: dict[str, str] = EQUITY_BRIDGE,
) -> pd.DataFrame:
    """One row per (date, index) with the weight-covered mean prediction.

    ``predictions`` must carry ``ts_code``, ``trade_date`` and the score column; rows whose
    score is not finite are treated as uncovered rather than as zero, which is the whole
    point of the coverage column.
    """
    rows: list[dict[str, object]] = []
    for date in dates:
        section = predictions[predictions["trade_date"] == date]
        if section.empty:
            continue
        score_by_code = dict(zip(section["ts_code"], section[prediction_column]))
        panel_mean = float(np.nanmean([v for v in score_by_code.values() if np.isfinite(v)]))
        for index_code, etf in bridge.items():
            weights = index_weights(con, index_code, date)
            if weights.empty:
                continue
            codes = weights["con_code"].tolist()
            weight = weights["weight"].to_numpy(dtype="float64")
            predicted = np.array(
                [score_by_code.get(code, np.nan) for code in codes], dtype="float64"
            )
            known = np.isfinite(predicted)
            total_weight = float(weight.sum())
            covered_weight = float(weight[known].sum())
            if covered_weight <= 0:
                score, coverage = float("nan"), 0.0
            else:
                score = float(np.dot(weight[known], predicted[known]) / covered_weight)
                coverage = covered_weight / total_weight if total_weight > 0 else 0.0
            rows.append(
                {
                    "trade_date": date,
                    "index_code": index_code,
                    "etf": etf,
                    "score": score,
                    "coverage": coverage,
                    "n_members": len(codes),
                    "n_predicted": int(known.sum()),
                    "common": panel_mean,
                    "deviation": score - panel_mean if np.isfinite(score) else float("nan"),
                    "weight_snapshot": str(weights["trade_date"].iloc[0]),
                    "weight_available": str(weights["available_date"].iloc[0]),
                }
            )
    return pd.DataFrame(rows)


def deviation_share(sleeves: pd.DataFrame) -> dict[str, float]:
    """Share of sleeve-score variance that is not shared across the three indices.

    Computed on the reported (coverage-gated) months only. A share near 0 means the three
    ETFs moved as one and the panel supplied nothing sleeve-specific; near 1 means the
    score is essentially a bet on the sleeve's own membership.
    """
    usable = sleeves[sleeves["coverage"] >= MIN_COVERAGE_TO_REPORT].copy()
    usable = usable[np.isfinite(usable["score"])]
    if len(usable) < 6:
        return {"deviation_share": float("nan"), "months": float(len(usable))}
    # Remove each index's own mean first: the question is about month-to-month variance
    # around the sleeve's average level, not about which index is systematically higher.
    demeaned = usable.copy()
    demeaned["score"] = demeaned["score"] - demeaned.groupby("index_code")["score"].transform("mean")
    raw_deviation = usable["score"] - usable["common"]
    demeaned["deviation"] = raw_deviation - raw_deviation.groupby(usable["index_code"]).transform("mean")
    total_var = float(np.var(demeaned["score"].to_numpy(), ddof=1))
    dev_var = float(np.var(demeaned["deviation"].to_numpy(), ddof=1))
    return {
        "deviation_share": dev_var / total_var if total_var > 0 else float("nan"),
        "months": float(len(usable)),
        "score_sd": float(np.std(demeaned["score"].to_numpy(), ddof=1)),
        "deviation_sd": float(np.std(demeaned["deviation"].to_numpy(), ddof=1)),
    }
