"""Does the same single-member truncation hit the BOND sleeve, and is it the lot there?

The overseas control found the cost gate, not the board lot, truncates that sleeve to one fund at
50 000 CNY, and that the truncation is worth 1.34-2.28 pp/yr per start.  The bond sleeve is the
opposite case by construction: 511220 is par-quoted, so one lot is about 9 985 CNY against a
4 000-7 000 CNY gate, while the sleeve's 35 % budget split two ways is about 8 750 CNY.  Half
the budget is therefore below one lot and above the gate - so if the lot is the binding term
anywhere in this book, it is here, and the prediction is exact:

  base      floor = max(gate, lot)  -> k = 1, orderings disperse
  gate_off  floor = lot only        -> k = 1 still, orderings disperse as in base
  lot_off   floor = gate only       -> k = 2 allowed, orderings inert, dispersion 0

which is the mirror image of the overseas result and would show the same phenomenon firing for
a different structural reason.

PRE-DECLARED:
  P0 base regime must show members_bond = 1 on every composition row at 50 000 CNY, else the
     arithmetic behind this probe is wrong and nothing is quotable.
  P1 dispersion across the two orderings of terminal NAV, (max-min)/mean in per-cent, per regime.
  DECIDE board-lot-binds-the-bond-sleeve if dispersion(lot_off) <= 0.2*base and
     dispersion(gate_off) >= 0.7*base; DECIDE gate-binds-everywhere if lot_off behaves like base;
     DECIDE neither if both are near zero.
"""

from __future__ import annotations

import itertools
import json
from decimal import Decimal
from pathlib import Path

import pandas as pd

import newquant.replay as rp
from newquant.replay import ARMS, build_market, replay, slippage_table, TRADED

NAV0 = Decimal("50000")
COST_MODE = "measured"
FIRST, END = "2016-01-04", "2026-11-04"
STARTS = ("2016-01-04", "2017-04-05", "2018-07-02",
          "2020-01-02", "2021-10-08", "2023-10-09")
BASE = ("511220", "511380")
TOL = Decimal("15.1")
WIDE = Decimal("1000000")
REGIMES = (("base", TOL, True), ("gate_off", WIDE, True), ("lot_off", TOL, False))
OUT = Path("evidence/probe-bond-control")
LEDGERS = Path("/d/tmp/rd_bond")

ORIG_FLOOR = rp.sleeve_floor


def floor_gate_only(market, codes, date, tol, slippage):
    need = Decimal("0")
    for code in codes:
        if market.mark(code, date) is None:
            continue
        need = max(need, rp.code_gate(code, tol, slippage))
    return need


def main() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    LEDGERS.mkdir(parents=True, exist_ok=True)
    market = build_market("data/etf_bars.parquet", "data/corp_actions.parquet",
                          "evidence/sleeve_scores.parquet", start=FIRST, end=END)
    orderings = list(itertools.permutations(BASE))
    original = rp.SLEEVE_MEMBERS["bond"]
    hold, years, cells, counts = {}, {}, {}, {}

    try:
        rp.SLEEVE_MEMBERS["bond"] = BASE
        for start in STARTS:
            res = replay(market, ARMS["hold"], nav0=NAV0, tolerance_bp=Decimal("200"),
                         cost_mode=COST_MODE, ledger_path=LEDGERS / f"hold__{start}.jsonl",
                         start=start, end=END)
            hold[start] = float(res.stats["nav_end"])
            d0 = pd.Timestamp(str(res.daily["date"].iloc[0]))
            d1 = pd.Timestamp(str(res.daily["date"].iloc[-1]))
            years[start] = max((d1 - d0).days / 365.25, 1e-9)

        for regime, tol, keep_lot in REGIMES:
            rp.sleeve_floor = ORIG_FLOOR if keep_lot else floor_gate_only
            cells[regime] = {}
            for order in orderings:
                rp.SLEEVE_MEMBERS["bond"] = order
                tag = "-".join(order)
                cells[regime][tag] = {}
                for start in STARTS:
                    res = replay(market, ARMS["lots"], nav0=NAV0, tolerance_bp=tol,
                                 cost_mode=COST_MODE,
                                 ledger_path=LEDGERS / f"{regime}__{tag}__{start}.jsonl",
                                 start=start, end=END)
                    nav = float(res.stats["nav_end"])
                    gap = ((hold[start] / nav) ** (1.0 / years[start]) - 1.0) * 100.0
                    mb = sorted({int(x) for x in res.monthly["members_bond"].tolist()})
                    counts.setdefault(regime, {}).setdefault(tag, {})[start] = mb
                    cells[regime][tag][start] = {
                        "nav_end": nav, "gap_pp_yr": gap,
                        "ovs_end": float(res.monthly.iloc[-1]["realised_bond"])}
                m = sum(cells[regime][tag][s]["gap_pp_yr"] for s in STARTS) / len(STARTS)
                print(f"[{regime}] {tag} mean gap {m:+.3f} pp/yr "
                      f"members_bond values {sorted(set().union(*counts[regime][tag].values()))}",
                      flush=True)
    finally:
        rp.sleeve_floor = ORIG_FLOOR
        rp.SLEEVE_MEMBERS["bond"] = original

    p0 = all(1 in counts["base"][t][s] and max(counts["base"][t][s]) == 1
             for t in counts["base"] for s in STARTS)
    disp, per_regime = {}, {}
    for regime, _, _ in REGIMES:
        per_start = {}
        for start in STARTS:
            navs = [cells[regime][t][start]["nav_end"] for t in cells[regime]]
            per_start[start] = (max(navs) - min(navs)) / (sum(navs) / len(navs)) * 100.0
        means = {t: sum(cells[regime][t][s]["gap_pp_yr"] for s in STARTS) / len(STARTS)
                 for t in cells[regime]}
        disp[regime] = sum(per_start.values()) / len(per_start)
        per_regime[regime] = {"dispersion_pct": disp[regime], "per_start_pct": per_start,
                              "order_means_pp": means,
                              "spread_pp": max(means.values()) - min(means.values()),
                              "members_bond": counts[regime]}

    b = disp["base"]
    if not p0:
        verdict = "invalid_experiment: base regime did not truncate the bond sleeve to one member"
    elif disp["lot_off"] <= 0.2 * b and disp["gate_off"] >= 0.7 * b:
        verdict = "board-lot-binds-the-bond-sleeve"
    elif disp["lot_off"] >= 0.7 * b:
        verdict = "gate-binds-this-sleeve-too"
    else:
        verdict = "neither-truncates: both regimes near zero dispersion"

    summary = {"probe": "bond-control", "nav0": float(NAV0), "starts": list(STARTS),
               "p0_base_members_bond_all_one": bool(p0),
               "dispersion_pct": disp, "per_regime": per_regime, "cells": cells,
               "verdict": verdict}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = ["# Bond sleeve: is the board lot the binding term here?", "",
             f"50 000 CNY, two orderings, {len(STARTS)} starts, three regimes. "
             f"P0 (base truncates to one member): {'yes' if p0 else 'NO'}.", "",
             "| regime | dispersion (%) | ratio to base | members_bond seen |",
             "|---|---|---|---|"]
    for regime, _, _ in REGIMES:
        seen = sorted({x for t in counts[regime] for s in counts[regime][t]
                       for x in counts[regime][t][s]})
        lines.append(f"| {regime} | {disp[regime]:.3f} | {disp[regime] / b:.2f} x | {seen} |")
    lines += ["", f"**Verdict:** {verdict}", ""]
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "p0": bool(p0),
                      "dispersion": {k: round(v, 3) for k, v in disp.items()}}, indent=2))
    return summary


if __name__ == "__main__":
    main()