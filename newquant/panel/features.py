"""Panel features at a signal date, with the causal direction enforced in SQL.

Rules this file obeys, and why each one is written down:

1. **Every feature is trailing.** Each window ends at the signal row (``rows between N
   preceding and current row``). A feature that peeked one row forward would score
   beautifully and be worthless, so the leakage test in ``tests/test_panel_features.py``
   perturbs the panel at ``t+1`` and requires the feature vector at ``t`` to be unchanged.
2. **The label is anchored after the entry, not at it.** ``open_adj[t+22] / open_adj[t+1]
   - 1``: the signal is formed on ``t``'s close, the order is filled at ``t+1``'s open, the
   holding period is 21 sessions. A label anchored at ``t``'s close would hand the model
   the entry bar it cannot trade.
3. **Missing is missing.** Nothing is filled with zero: a zero is a legitimate value of a
   z-scored feature, so ``fillna(0)`` (the local AlphaGPT convention at
   ``ashare_model/factors.py:227``) makes "no data" and "exactly average" indistinguishable
   and lets a model learn from a stock's *absence*. Downstream code carries an explicit
   finite mask instead.
4. **Weights are pulled by ``available_date``, once per date, in ``aggregate.py``** — not
   here. Feature engineering never needs a constituent list, and keeping it out means a
   membership bug cannot contaminate a feature.

Prices are adjusted by ``adj_factor`` *per bar*, so a split inside the lookback does not
appear as a −50 % return; the entry/exit endpoints of the label use the adjusted open for
the same reason.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

# Calendar days a signal may look back over, for the bar load. 252 sessions ≈ 1 year of
# data before the first signal date; two extra years of slack absorb suspensions.
LOOKBACK_SLACK_DAYS = 500

FEATURES: tuple[str, ...] = (
    "ret_1w",
    "ret_1m",
    "ret_6m",
    "ret_12_1",
    "vol_21",
    "vol_63",
    "turnover_21",
    "turnover_chg",
    "log_mv",
    "ep",
    "bp",
    "mom_52w",
    "illiq_21",
    "list_age_yr",
)

# Winsorise at the 1 %/99 % quantiles of each date's cross-section, then (x - median)/MAD,
# clipped at 5. This is the local panel's own convention (`ashare_data/processor.py:651`),
# reproduced rather than imported so E1 has one definition of "standardised".
WINSOR_Q = (0.01, 0.99)
MAD_CLIP = 5.0

_FEATURE_SQL = """
WITH bars AS (
    SELECT b.ts_code, b.trade_date, b.open, b.amount,
           b.close * f.adj_factor AS close_adj,
           b.open  * f.adj_factor AS open_adj
    FROM daily_bar_raw b
    JOIN daily_adj_factor f USING (ts_code, trade_date)
    WHERE b.trade_date BETWEEN ? AND ?
),
flags AS (
    SELECT b.ts_code, b.trade_date,
           CASE WHEN s.ts_code IS NOT NULL THEN TRUE
                WHEN l.up_limit IS NOT NULL AND b.open >= l.up_limit THEN TRUE
                ELSE FALSE END AS entry_blocked
    FROM daily_bar_raw b
    LEFT JOIN daily_price_limit l USING (ts_code, trade_date)
    LEFT JOIN daily_suspension  s USING (ts_code, trade_date)
    WHERE b.trade_date BETWEEN ? AND ?
),
joined AS (
    SELECT b.*, f.entry_blocked,
           d.turnover_rate, d.total_mv, d.pe_ttm, d.pb,
           b.close_adj / lag(b.close_adj) OVER w AS r
    FROM bars b
    JOIN flags f USING (ts_code, trade_date)
    LEFT JOIN daily_basic_pit d USING (ts_code, trade_date)
    WINDOW w AS (PARTITION BY b.ts_code ORDER BY b.trade_date)
),
calc AS (
    SELECT *,
        lead(open_adj, 1)  OVER w AS open_t1,
        lead(open_adj, 22) OVER w AS open_t22,
        lead(entry_blocked, 1) OVER w AS blocked_t1,
        close_adj / lag(close_adj, 5)   OVER w - 1 AS ret_1w,
        close_adj / lag(close_adj, 21)  OVER w - 1 AS ret_1m,
        close_adj / lag(close_adj, 126) OVER w - 1 AS ret_6m,
        lag(close_adj, 21) OVER w / lag(close_adj, 252) OVER w - 1 AS ret_12_1,
        stddev_samp(r) OVER (w ROWS BETWEEN 20 PRECEDING AND CURRENT ROW) AS vol_21,
        stddev_samp(r) OVER (w ROWS BETWEEN 62 PRECEDING AND CURRENT ROW) AS vol_63,
        avg(turnover_rate) OVER (w ROWS BETWEEN 20 PRECEDING AND CURRENT ROW) AS turnover_21,
        avg(turnover_rate) OVER (w ROWS BETWEEN 125 PRECEDING AND CURRENT ROW) AS turnover_126,
        close_adj / max(close_adj) OVER (
            w ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS mom_52w,
        avg(abs(r) / nullif(amount, 0)) OVER (
            w ROWS BETWEEN 20 PRECEDING AND CURRENT ROW) AS illiq_21,
        -- Completeness of each window. An average over three observations is not a 21-day
        -- average, it is a number wearing one as a label; short windows are returned as
        -- missing instead, so the coverage mask downstream is honest.
        count(r) OVER (w ROWS BETWEEN 20 PRECEDING AND CURRENT ROW) AS n_r_21,
        count(r) OVER (w ROWS BETWEEN 62 PRECEDING AND CURRENT ROW) AS n_r_63,
        count(turnover_rate) OVER (w ROWS BETWEEN 20 PRECEDING AND CURRENT ROW) AS n_turn_21,
        count(turnover_rate) OVER (w ROWS BETWEEN 125 PRECEDING AND CURRENT ROW) AS n_turn_126,
        count(close_adj) OVER (w ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS n_c_252,
        count(abs(r) / nullif(amount, 0)) OVER (
            w ROWS BETWEEN 20 PRECEDING AND CURRENT ROW) AS n_illiq_21
    FROM joined
    WINDOW w AS (PARTITION BY ts_code ORDER BY trade_date)
)
SELECT c.ts_code, c.trade_date,
       c.open_t22 / c.open_t1 - 1.0        AS label,
       CAST(NOT coalesce(c.blocked_t1, TRUE) AS BOOLEAN) AS entry_ok,
       c.ret_1w, c.ret_1m, c.ret_6m,
       CASE WHEN c.ret_12_1 > -0.95 THEN c.ret_12_1 END AS ret_12_1,
       CASE WHEN c.n_r_21 >= 15 THEN c.vol_21 END AS vol_21,
       CASE WHEN c.n_r_63 >= 45 THEN c.vol_63 END AS vol_63,
       CASE WHEN c.n_turn_21 >= 15 THEN c.turnover_21 END AS turnover_21,
       CASE WHEN c.n_turn_126 >= 90 AND c.turnover_126 > 0
            THEN c.turnover_21 / c.turnover_126 - 1.0 END AS turnover_chg,
       CASE WHEN c.total_mv > 0 THEN ln(c.total_mv) END AS log_mv,
       CASE WHEN c.pe_ttm > 0 THEN 1.0 / c.pe_ttm END   AS ep,
       CASE WHEN c.pb > 0 THEN 1.0 / c.pb END           AS bp,
       CASE WHEN c.n_c_252 >= 200 THEN c.mom_52w END AS mom_52w,
       CASE WHEN c.n_illiq_21 >= 15 THEN c.illiq_21 END AS illiq_21,
       date_diff('day', strptime(s.list_date, '%Y%m%d'),
                 strptime(c.trade_date, '%Y%m%d')) / 365.25 AS list_age_yr
FROM calc c
LEFT JOIN stocks s ON s.ts_code = c.ts_code
WHERE c.trade_date IN (SELECT * FROM unnest(?))
"""


def _shift_date(date: str, days: int) -> str:
    """YYYYMMDD arithmetic on calendar days, without pulling in a date library."""
    ts = pd.Timestamp(date) + pd.Timedelta(days=days)
    return ts.strftime("%Y%m%d")


def build(
    con: duckdb.DuckDBPyConnection,
    signal_dates: list[str],
    *,
    standardise: bool = True,
    codes: list[str] | None = None,
    chunk_months: int = 24,
) -> pd.DataFrame:
    """Long frame: one row per (ts_code, signal date) with features, label and masks.

    ``entry_ok`` is the T+1 fill gate (not suspended, open below the up-limit). A row with
    ``entry_ok == False`` keeps its features but is excluded from training and from every
    scored aggregate, because a prediction for a name you cannot buy is not a prediction
    about the sleeve.
    """
    if not signal_dates:
        return pd.DataFrame(columns=("ts_code", "trade_date", "label", "entry_ok", *FEATURES))
    chunks = [
        sorted(signal_dates)[i : i + chunk_months]
        for i in range(0, len(signal_dates), chunk_months)
    ]
    pieces = []
    for chunk in chunks:
        lo = _shift_date(min(chunk), -LOOKBACK_SLACK_DAYS)
        hi = _shift_date(max(chunk), 60)
        suffix = ""
        if codes:
            suffix = " AND c.ts_code IN (SELECT * FROM unnest(?))"
        params = [lo, hi, lo, hi, chunk] + ([codes] if codes else [])
        pieces.append(con.execute(_FEATURE_SQL + suffix, params).df())
    frame = pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()
    frame["trade_date"] = frame["trade_date"].astype(str)
    for name in FEATURES:
        frame[name] = pd.to_numeric(frame[name], errors="coerce").astype("float64")
    if standardise:
        frame = cross_sectional_z(frame, FEATURES)
    return frame


def cross_sectional_z(
    frame: pd.DataFrame, columns: tuple[str, ...] = FEATURES, *, clip: float = MAD_CLIP
) -> pd.DataFrame:
    """Winsorise → median/MAD → clip, per date, per column.

    MAD is scaled by 1.4826 so a Gaussian has unit scale and a z of 1 means the same thing
    on every date. When MAD is zero (a column that is constant across the section, e.g. a
    block of equally valued bond-like names) the fallback is the plain standard deviation,
    and if that is zero too the column is left undefined rather than divided by zero.
    """
    out = frame.copy()
    grouped = out.groupby("trade_date", observed=True)
    for name in columns:
        values = out[name]
        if values.notna().sum() == 0:
            continue
        lo = grouped[name].transform(lambda s: s.quantile(WINSOR_Q[0]))
        hi = grouped[name].transform(lambda s: s.quantile(WINSOR_Q[1]))
        clipped = values.clip(lower=lo, upper=hi)
        median = clipped.groupby(out["trade_date"], observed=True).transform("median")
        mad = (clipped - median).abs().groupby(out["trade_date"], observed=True).transform("median") * 1.4826
        sd = clipped.groupby(out["trade_date"], observed=True).transform("std")
        scale = mad.where(mad > 1e-12, sd)
        out[name] = ((clipped - median) / scale.where(scale > 1e-12)).clip(-clip, clip)
    return out


def apply_mask(frame: pd.DataFrame, columns: tuple[str, ...] = FEATURES) -> pd.DataFrame:
    """Attach ``n_finite`` = how many features a row actually has.

    Carried into training so a row with one usable feature is not treated like a complete
    one; the ridge fit weights rows by coverage and the MLP drops rows below the floor.
    """
    out = frame.copy()
    out["n_finite"] = np.isfinite(out[list(columns)].to_numpy(dtype="float64")).sum(axis=1)
    return out


MIN_FEATURES_FOR_TRAINING = 6
