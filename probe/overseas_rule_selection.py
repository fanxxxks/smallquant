"""Can an ex-ante rule name the overseas fund the shipped tuple happens to name first?

`lot_composition` keeps `available[:k]` (newquant/replay.py:403), and at 50 000 CNY the overseas
sleeve clears the floor only at k = 1, so the tuple position *is* the investment decision.  The
shipped tuple puts 513100 first, and the permutation probe (evidence/probe-member-order) showed
that ordering is worth 1.74 pp/yr across 6 starts - i.e. the decision is large enough to matter
and the tuple is not a rule.

So the question is not whether the ordering matters but whether any rule that uses only
information available at the entry date lands on the same fund.  The cheapest rule in reach is
liquidity: rank the sleeve's members by median turnover (`amount`) over the sessions before the
entry and put the deepest market first.  That is defensible on its own terms (an order that the
gate admits still has to fill) and, unlike the shipped tuple, it is stated.

KILL CONDITION, pre-declared: if the liquidity rule lands on a nav at or below the 159920-first
ordering at 4 of the 6 starts, the rule does not recover the shipped advantage and the direction
- "just state an ex-ante member rule" - is dead as a way to keep the construction's edge.  If it
lands between the extreme orderings, the rule is a candidate and deserves the 32-start grid.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pandas as pd

import newquant.replay as rp
from newquant.replay import ARMS, build_market, replay

NAV0 = Decimal("50000")
COST_MODE = "measured"
FIRST, END = "2016-01-04", "2026-11-04"
OUT = Path("evidence/probe-overseas-rule")
LEDGERS = Path("/tmp/rd_rule")
PERM = Path("evidence/probe-member-order/summary.json")

OVERSEAS = ("513100", "513500", "159920")
STARTS = ("2016-01-04", "2017-04-05", "2018-07-02",
          "2020-01-02", "2021-10-08", "2023-10-09")
LOOKBACK = 120


def liquidity_order(bars: pd.DataFrame, start: str) -> tuple[tuple[str, ...], dict[str, float]]:
    hist = bars[bars["date"] < start]
    sess = sorted(hist["date"].unique())[-LOOKBACK:]
    recent = hist[hist["date"].isin(sess)]
    depth = {c: float(recent.loc[recent["code"] == c, "amount"].median() or 0.0)
             for c in OVERSEAS}
    order = tuple(sorted(OVERSEAS, key=lambda c: -depth[c]))
    return order, depth


def main() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    LEDGERS.mkdir(parents=True, exist_ok=True)
    bars = pd.read_parquet("data/etf_bars.parquet").reset_index()
    bars["date"] = pd.to_datetime(bars["date"]).dt.strftime("%Y-%m-%d")
    perm = json.loads(PERM.read_text(encoding="utf-8"))
    extremes = {o["tag"]: o["gap_mean_pp"] for o in perm["per_order"]}
    hold200 = {p["start"]: p["hold200_nav"]
               for o in perm["per_order"] if o["tag"] == "513100-513500-159920"
               for p in o["pairs"]}
    worst_first = {p["start"]: p["lots_nav"]
                   for o in perm["per_order"] if o["tag"] == "159920-513100-513500"
                   for p in o["pairs"]}
    best_first = {p["start"]: p["lots_nav"]
                  for o in perm["per_order"] if o["tag"] == "513100-513500-159920"
                  for p in o["pairs"]}

    market = build_market("data/etf_bars.parquet", "data/corp_actions.parquet",
                          "evidence/sleeve_scores.parquet", start=FIRST, end=END)
    original = rp.SLEEVE_MEMBERS["overseas"]
    rows = []
    try:
        for start in STARTS:
            order, depth = liquidity_order(bars, start)
            rp.SLEEVE_MEMBERS["overseas"] = order
            res = replay(market, ARMS["lots"], nav0=NAV0, tolerance_bp=Decimal("15.1"),
                         cost_mode=COST_MODE, ledger_path=LEDGERS / f"liq__{start}.jsonl",
                         start=start, end=END)
            nav = float(res.stats["nav_end"])
            bought = sorted(set(res.fills.loc[res.fills["side"] == "buy", "code"])
                            & set(OVERSEAS))
            rows.append({"start": start, "order": list(order),
                         "depth_cny": {c: round(v, 0) for c, v in depth.items()},
                         "nav": nav, "overseas_bought": bought,
                         "nav_shipped_first": best_first[start],
                         "nav_worst_first": worst_first[start],
                         "hold200": hold200[start],
                         "at_or_below_worst": nav <= worst_first[start] + 1.0})
            print(f"{start} order={order} nav={nav:,.0f} "
                  f"shipped={best_first[start]:,.0f} worst={worst_first[start]:,.0f} "
                  f"hold200={hold200[start]:,.0f}", flush=True)
    finally:
        rp.SLEEVE_MEMBERS["overseas"] = original

    n_bad = sum(1 for r in rows if r["at_or_below_worst"])
    verdict = ("rule does not recover the shipped advantage (killed)"
               if n_bad >= 4 else "rule lands inside the ordering range (candidate)")
    out = {"probe": "overseas-rule-selection", "rule": "median amount over 120 sessions",
           "starts": list(STARTS), "cells": rows,
           "summary": {"n_at_or_below_worst_first": n_bad, "verdict": verdict,
                       "orderings_from_permutation_pp": extremes}}
    (OUT / "summary.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(verdict)
    return out


if __name__ == "__main__":
    main()