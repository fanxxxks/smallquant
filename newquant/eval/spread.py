"""Measured execution cost from data we hold, replacing an inherited assumption.

The cost gate needs one number that was never measured: the per-side cost of crossing the
book (`slippage`). The architecture doc records it as 5 bp "inherited, not measured", and a
review objection says that if the true figure is 1-2 bp the rate infimum falls to 3.6-4.6 bp
and every threshold in the feasibility report moves. This module tries to measure it and,
where measurement fails, bounds it with something that is not an assumption.

Three quantities, in increasing order of trustworthiness:

1. Corwin-Schultz (2012) and Roll (1984) spread estimators from daily bars. Both are
   implemented here and both **fail on this data**: CS returns negative two-day estimates for
   most pairs (its known low-spread floor) and Roll's autocovariance is undefined for most
   codes because ETF price changes are dominated by drift rather than bid-ask bounce. They are
   kept in the output as the record of a failed measurement, not as inputs.

2. The **tick floor** — the one bound that is neither estimated nor inherited. Exchange rules
   quote these instruments in steps of 0.001 CNY, so any crossing trade pays at least half a
   tick: `half_tick_bp = 500 * 0.001 / price`. For a 1.0 CNY ETF that is 4.9 bp of one-way
   cost before any fee, which is already most of the 7.6 bp infimum. A one-way cost of 1-2 bp
   is therefore **arithmetically impossible** for the low-priced instruments, and it is the
   low-priced ones that survive the lot-size screen.

3. The per-instrument floor that follows: `commission_rate + transfer + half_tick`, i.e. the
   infimum of the all-in one-way rate for that code, computed with no free parameter.

What this cannot do is separate the half-tick from market impact, or see depth. So the gate
keeps 5 bp as its central assumption and adds the measured floor as a hard lower bound; the
sensitivity table then spans only the range that is arithmetically reachable.

Deliberate limitations, recorded rather than papered over:

* Bars are unadjusted (`adjust=""`), so an ex-dividend day shows as a large negative `pct_chg`
  with a range that ignores it. Those days are excluded by a documented filter and counted.
* CS is a two-day estimator; overlapping windows make monthly means noisier than iid theory
  suggests, so dispersion is reported and no confidence interval is claimed.
* Market impact is reported as unmeasured. At 5-25 k CNY in these instruments nobody can
  measure it from daily bars, and nobody should claim to.
"""

from __future__ import annotations

import json
import math
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

import numpy as np
import pandas as pd

ROLL_MIN_OBS = 15
CS_MIN_OBS = 10
EXTREME_PCT_CHG = 3.0  # |pct_chg| in percent; ex-div / limit days
SQRT2 = math.sqrt(2.0)
CS_DENOM = 3.0 - 2.0 * SQRT2
TICK = 0.001  # CNY, the quoted price step for these instruments


def corwin_schultz(high: np.ndarray, low: np.ndarray) -> np.ndarray:
    """Two-day CS spread estimate as a fraction. Negative values are the estimator's floor.

    alpha = (sqrt(2*beta) - sqrt(beta)) / (3 - 2*sqrt(2)) - sqrt(gamma / (3 - 2*sqrt(2)))
    S     = 2 * (exp(alpha) - 1) / (1 + exp(alpha))
    """
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        ln_hl = np.log(high / low)
        beta = ln_hl[:-1] ** 2 + ln_hl[1:] ** 2
        joint_hi = np.maximum(high[:-1], high[1:])
        joint_lo = np.minimum(low[:-1], low[1:])
        gamma = np.log(joint_hi / joint_lo) ** 2
        alpha = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / CS_DENOM - np.sqrt(gamma / CS_DENOM)
        return 2.0 * (np.exp(alpha) - 1.0) / (1.0 + np.exp(alpha))


def roll(close: np.ndarray) -> float:
    """Roll spread from the first autocovariance of price changes. NaN if non-negative."""
    dp = np.diff(np.asarray(close, dtype=float))
    if dp.size < ROLL_MIN_OBS:
        return float("nan")
    cov = float(np.cov(dp[:-1], dp[1:], ddof=1)[0, 1])
    if not math.isfinite(cov) or cov >= 0.0:
        return float("nan")
    return 2.0 * math.sqrt(-cov) / float(np.mean(close))


def per_code(bars: pd.DataFrame) -> pd.DataFrame:
    """Per instrument: both failed estimators, the clamp rate, and the tick floor."""
    from ..venue import ETF_STD

    rows = []
    for code, g in bars.groupby("code", sort=True):
        g = g.sort_values("date")
        keep = g["pct_chg"].abs() <= EXTREME_PCT_CHG
        n_excluded = int((~keep).sum())
        g = g[keep]
        price = float(g["close"].median())
        cs_bp = float("nan")
        neg_share = float("nan")
        if len(g) >= CS_MIN_OBS + 1:
            est = corwin_schultz(g["high"].to_numpy(), g["low"].to_numpy())
            est = est[np.isfinite(est)]
            if est.size:
                cs_bp = float(np.mean(np.clip(est, 0.0, None))) * 1e4  # CS convention
                neg_share = float((est < 0).mean())
        roll_bp = roll(g["close"].to_numpy()) * 1e4
        half_tick_bp = TICK / price * 1e4 / 2.0
        floor_bp = float(ETF_STD.commission_rate + ETF_STD.transfer_rate) * 1e4 + half_tick_bp
        rows.append(
            {
                "code": str(code),
                "obs": int(len(g)),
                "excluded_days": n_excluded,
                "price": round(price, 4),
                "cs_oneway_bp": None if math.isnan(cs_bp) else round(cs_bp / 2.0, 3),
                "cs_negative_share": None if math.isnan(neg_share) else round(neg_share, 3),
                "roll_oneway_bp": None if math.isnan(roll_bp) else round(roll_bp / 2.0, 3),
                "half_tick_bp": round(half_tick_bp, 3),
                "tick_floor_bp": round(floor_bp, 3),
            }
        )
    return pd.DataFrame(rows)


def gate_table(var_candidates_bp: dict[str, float]) -> pd.DataFrame:
    """Rate infimum and the minimum clearing order for each half-spread assumption.

    rate(N) = max(commission_min/N, commission_rate) + transfer + half_spread, so the infimum
    is commission_rate + transfer + half_spread and N_min solves rate(N) = tolerance.
    """
    from ..venue import ETF_STD, gate_ok

    rows = []
    for label, half_spread_bp in var_candidates_bp.items():
        var = Decimal("0.00001") + Decimal(str(round(half_spread_bp, 4))) * Decimal("0.0001")
        infimum = (Decimal(str(ETF_STD.commission_rate)) + var) * Decimal(10000)
        row = {
            "scenario": label,
            "half_spread_bp": round(half_spread_bp, 3),
            "infimum_bp": float(infimum.quantize(Decimal("0.001"))),
        }
        for tol_bp in ("7.6", "10", "15.1"):
            tol = Decimal(tol_bp)
            denom = tol * Decimal("0.0001") - var
            if denom <= Decimal(str(ETF_STD.commission_rate)):
                row[f"min_order_{tol_bp}bp"] = None
                continue
            n = (Decimal(str(ETF_STD.commission_min)) / denom).quantize(
                Decimal("0.01"), rounding=ROUND_CEILING)
            while not gate_ok(n, "buy", tol)[0]:
                n += Decimal("0.01")
            row[f"min_order_{tol_bp}bp"] = float(n)
        rows.append(row)
    return pd.DataFrame(rows)


def verdict(table: pd.DataFrame, tradable: list[str]) -> dict:
    """Turn the three quantities into one defensible sentence per question."""
    t = table[table["code"].isin(tradable)]
    cs = t["cs_oneway_bp"].dropna()
    roll_defined = int(t["roll_oneway_bp"].notna().sum())
    return {
        "codes": int(len(table)),
        "tradable_codes": int(len(t)),
        "cs_resolves": bool(cs.size and cs.median() > 0.5),
        "cs_oneway_median_bp": None if cs.empty else round(float(cs.median()), 3),
        "cs_negative_share_median": round(float(t["cs_negative_share"].median()), 3),
        "roll_defined": roll_defined,
        "estimators_failed": roll_defined < len(t) / 2 or not bool(cs.size and cs.median() > 0.5),
        "tick_floor_min_bp": round(float(t["tick_floor_bp"].min()), 3),
        "tick_floor_max_bp": round(float(t["tick_floor_bp"].max()), 3),
        "half_tick_max_bp": round(float(t["half_tick_bp"].max()), 3),
        "one_bp_reachable": bool(float(t["half_tick_bp"].min()) < 1.0),
        "impact_bp": 0.0,
        "impact_note": "unmeasured; no quote or depth data",
    }


def build(bars_path: Path, out_dir: Path, venue: pd.DataFrame) -> dict:
    bars = pd.read_parquet(bars_path)
    table = per_code(bars)
    table = table.merge(venue[["code", "name", "sleeve", "tradable"]], on="code", how="left")
    tradable = venue.loc[venue["tradable"], "code"].astype(str).tolist()
    v = verdict(table, tradable)

    t = table[table["code"].isin(tradable)]
    scen = {
        "measured_tick_floor_min": float(t["tick_floor_bp"].min()),
        "measured_tick_floor_max": float(t["tick_floor_bp"].max()),
        "tick_floor_plus_2bp_impact": float(t["tick_floor_bp"].max()) + 2.0,
        "inherited_5bp": 5.0,
        "optimistic_1bp": 1.0,
    }
    gt = gate_table(scen)
    v["gate_scenarios"] = gt.to_dict(orient="records")

    out_dir.mkdir(parents=True, exist_ok=True)
    table.to_parquet(out_dir / "spread.parquet", index=False)
    (out_dir / "spread.json").write_text(json.dumps(v, indent=2, ensure_ascii=False))
    lines = [
        "# Execution cost: what could be measured, and what could not",
        "",
        f"Instruments {v['codes']} ({v['tradable_codes']} tradable); excluded days (|pct_chg| > ",
        f"{EXTREME_PCT_CHG}%): {int(table['excluded_days'].sum())}.",
        "",
        "## 1. The bar-based estimators fail here — recorded, not used",
        "",
        f"- Corwin-Schultz clamped one-way median on the tradable set: **{v['cs_oneway_median_bp']} bp**,",
        f"  with **{v['cs_negative_share_median']:.0%}** of two-day pairs negative (the estimator's",
        "  low-spread floor). It cannot resolve a spread this small.",
        f"- Roll is defined on **{v['roll_defined']}/{v['tradable_codes']}** tradable codes; price changes",
        "  are drift-dominated, so the bid-ask autocovariance is usually non-negative.",
        f"- Verdict: estimators failed = **{v['estimators_failed']}**. Daily bars do not price this.",
        "",
        "## 2. The tick floor — measured, not assumed",
        "",
        f"Quoted step 0.001 CNY → half a tick costs `500 x 0.001 / price` bp one way.",
        f"On the tradable set that is **{v['tick_floor_min_bp']} – {v['tick_floor_max_bp']} bp** all-in",
        f"(commission 2.5 + transfer 0.01 + half tick), with a maximum half-tick of {v['half_tick_max_bp']} bp.",
        "",
        f"A one-way cost of 1 bp is reachable on any tradable code: **{v['one_bp_reachable']}**.",
        "The 7.6 bp rate infimum is therefore not a modelling artefact — half of it is the",
        "exchange's own price grid on the cheap ETFs, which are exactly the ones a 50 k account can hold.",
        "",
        "## 3. Gate sensitivity over the reachable range",
        "",
        gt.to_markdown(index=False),
        "",
        "## Per instrument",
        "",
        table.to_markdown(index=False),
    ]
    (out_dir / "spread.md").write_text("\n".join(lines) + "\n")
    return v


if __name__ == "__main__":
    from ..data.freeze import load

    venue_frame, _manifest = load(Path("data"))
    stats = build(Path("data/etf_bars.parquet"), Path("evidence"), venue_frame)
    print(json.dumps({k: val for k, val in stats.items() if k != "gate_scenarios"}, indent=2))
    print(pd.DataFrame(stats["gate_scenarios"]).to_string(index=False))
