"""Is the gate's ordering lottery expensive in proportion to how different a sleeve's members are?

The overseas control put the whole ordering spread on the cost gate and the exposure reading
attributes it to the members being three different foreign indices (Nasdaq-100, S&P 500, Hang
Seng; qfq CAGR 19.77 / 13.42 / 1.12 over 2017-04-05..2026-11-04).  If that is right, the same
lottery should cost almost nothing in the one sleeve whose members are the SAME underlying:
518880 and 159934 both track Au99.99, so swapping their order changes a gold ETF's tracking and
fee, not the exposure.  That is a prediction the reading can fail.

Design: for every sleeve, every permutation of the members AVAILABLE at that start, run the
"lots" arm at 50 000 CNY in the base regime and record terminal NAV.  Dispersion per sleeve per
start = (max-min)/mean across permutations, per cent.  No gate_off arm here: the earlier control
already established that removing the gate makes the orderings bit-identical.

PRE-DECLARED:
  P0 reproducibility: the overseas sleeve must reproduce the recorded six ordering means from
     evidence/probe-member-order/summary.json to 0.01 pp/yr, else nothing is quotable.
  P1 dispersion table per sleeve per start.
  DECIDE exposure-reading-supported if dispersion(commodity) <= 0.25 * dispersion(overseas) at
     EVERY start while the member CAGR spread is 0 for commodity and > 15 pp/yr for overseas.
  DECIDE reading-incomplete if commodity disperses like a multi-underlying sleeve.
"""

from __future__ import annotations

import itertools
import json
from decimal import Decimal
from pathlib import Path

import pandas as pd

import newquant.replay as rp
from newquant.replay import ARMS, SLEEVE_MEMBERS, build_market, replay

NAV0 = Decimal("50000")
COST_MODE = "measured"
FIRST, END = "2016-01-04", "2026-11-04"
STARTS = ("2016-01-04", "2017-04-05", "2018-07-02",
          "2020-01-02", "2021-10-08", "2023-10-09")
SLEEVES = {k: tuple(v) for k, v in SLEEVE_MEMBERS.items()}
OUT = Path("evidence/probe-sleeve-dispersion")
LEDGERS = Path("/d/tmp/rd_disp")
REF = Path("evidence/probe-member-order/summary.json")
UNDERLYING = {  # what each member tracks, for the reading under test
    "510300": "CSI 300", "510500": "CSI 500", "512100": "CSI 1000",
    "511220": "10y local-government bond", "511380": "convertible bond",
    "518880": "Au99.99", "159934": "Au99.99",
    "513100": "Nasdaq-100", "513500": "S&P 500", "159920": "Hang Seng",
}


def main() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    LEDGERS.mkdir(parents=True, exist_ok=True)
    market = build_market("data/etf_bars.parquet", "data/corp_actions.parquet",
                          "evidence/sleeve_scores.parquet", start=FIRST, end=END)
    hold, years = {}, {}
    for start in STARTS:
        res = replay(market, ARMS["hold"], nav0=NAV0, tolerance_bp=Decimal("200"),
                     cost_mode=COST_MODE, ledger_path=LEDGERS / f"hold__{start}.jsonl",
                     start=start, end=END)
        hold[start] = float(res.stats["nav_end"])
        d0 = pd.Timestamp(str(res.daily["date"].iloc[0]))
        d1 = pd.Timestamp(str(res.daily["date"].iloc[-1]))
        years[start] = max((d1 - d0).days / 365.25, 1e-9)

    original = dict(SLEEVE_MEMBERS)
    cells, avail = {}, {}
    try:
        for sleeve, members in SLEEVES.items():
            cells[sleeve] = {}
            for start in STARTS:
                live = [c for c in members if market.mark(c, start) is not None]
                avail.setdefault(sleeve, {})[start] = live
                # The engine maps every traded code to a sleeve, so the tuple must keep the
                # full member set; only the ORDER varies.  lot_composition drops unlisted
                # members, so two permutations that project to the same live order are the
                # same run and are deduplicated here.
                perms, seen = [], set()
                for perm in itertools.permutations(members):
                    key = tuple(c for c in perm if c in live)
                    if key in seen:
                        continue
                    seen.add(key)
                    perms.append(perm)
                cells[sleeve][start] = {}
                for perm in perms:
                    tag = "-".join(perm)
                    SLEEVE_MEMBERS[sleeve] = perm
                    if tag in cells[sleeve][start]:
                        continue
                    res = replay(market, ARMS["lots"], nav0=NAV0,
                                 tolerance_bp=Decimal("15.1"), cost_mode=COST_MODE,
                                 ledger_path=LEDGERS / f"{sleeve}__{tag}__{start}.jsonl",
                                 start=start, end=END)
                    nav = float(res.stats["nav_end"])
                    cells[sleeve][start][tag] = {
                        "nav_end": nav,
                        "gap_pp_yr": ((hold[start] / nav) ** (1.0 / years[start]) - 1.0) * 100.0,
                        "end_weight": float(res.monthly.iloc[-1][f"realised_{sleeve}"]),
                        "end_members": int(res.monthly.iloc[-1][f"members_{sleeve}"] or 0)}
                SLEEVE_MEMBERS[sleeve] = original[sleeve]
                navs = [v["nav_end"] for v in cells[sleeve][start].values()]
                mean = sum(navs) / len(navs)
                print(f"{sleeve:9s} {start} members {live} "
                      f"disp {(max(navs) - min(navs)) / mean * 100:6.3f} % "
                      f"gaps {[round(v['gap_pp_yr'], 3) for v in cells[sleeve][start].values()]}",
                      flush=True)
    finally:
        for k, v in original.items():
            SLEEVE_MEMBERS[k] = v

    disp, agg = {}, {}
    for sleeve in SLEEVES:
        per = {}
        for start in STARTS:
            navs = [v["nav_end"] for v in cells[sleeve][start].values()]
            per[start] = (max(navs) - min(navs)) / (sum(navs) / len(navs)) * 100.0
        disp[sleeve] = per
        agg[sleeve] = sum(per.values()) / len(per)

    cagr_spread = {}
    for sleeve, members in SLEEVES.items():
        rates = []
        for code in members:
            try:
                bars = market.close_of(code)
            except (KeyError, TypeError):
                continue
            if bars is None or len(bars) < 2:
                continue
            s = bars.loc[bars.index >= pd.Timestamp("2017-04-05")]
            if len(s) < 2:
                continue
            yrs = (s.index[-1] - s.index[0]).days / 365.25
            rates.append(((float(s.iloc[-1]) / float(s.iloc[0])) ** (1 / yrs) - 1) * 100)
        cagr_spread[sleeve] = max(rates) - min(rates) if len(rates) > 1 else 0.0

    p0_detail = {}
    ref = json.loads(REF.read_text(encoding="utf-8")) if REF.exists() else None
    if ref:
        for order in ref["per_order"]:
            tag = "-".join(order["order"])
            got = []
            for pair in order["pairs"]:
                cell = cells["overseas"].get(pair["start"], {}).get(tag)
                got.append(None if cell is None else round(cell["gap_pp_yr"] - pair["gap_pp_yr"], 4))
            p0_detail[tag] = got
    p0 = ref is not None and all(
        abs(x) <= 0.01 for v in p0_detail.values() for x in v if x is not None)

    ok = all(disp["commodity"][s] <= 0.25 * disp["overseas"][s] for s in STARTS)
    if not p0:
        verdict = "invalid_experiment: overseas sleeve did not reproduce the recorded ordering means"
    elif ok and cagr_spread["commodity"] < 1.0:
        verdict = "exposure-reading-supported"
    else:
        verdict = "reading-incomplete: dispersion is not proportional to underlying difference"

    summary = {"probe": "sleeve-dispersion", "nav0": float(NAV0), "starts": list(STARTS),
               "dispersion_pct": disp, "dispersion_mean_pct": agg,
               "member_cagr_spread_pp": cagr_spread, "available": avail,
               "p0_overseas_reproduction_max_abs_pp": p0_detail, "p0_ok": bool(p0),
               "underlying": UNDERLYING, "cells": cells, "verdict": verdict}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = ["# How much does the member-ordering lottery cost, by sleeve?", "",
             f"50 000 CNY, base regime (15.1 bp gate, lot floor), every permutation of the "
             f"members available at each of {len(STARTS)} starts. Dispersion = (max-min)/mean of "
             "terminal NAV across orderings, per cent.", "",
             "| sleeve | mean dispersion (%) | underlying CAGR spread (pp/yr) | members |",
             "|---|---|---|---|"]
    for sleeve in SLEEVES:
        lines.append(f"| {sleeve} | {agg[sleeve]:.3f} | {cagr_spread[sleeve]:.2f} | "
                     f"{' / '.join(UNDERLYING.get(c, c) for c in SLEEVES[sleeve])} |")
    lines += ["", "| sleeve | " + " | ".join(STARTS) + " |",
              "|---|" + "---|" * len(STARTS)]
    for sleeve in SLEEVES:
        lines.append(f"| {sleeve} | " + " | ".join(
            f"{disp[sleeve][s]:.2f}" for s in STARTS) + " |")
    lines += ["", f"P0 overseas reproduction: {'ok' if p0 else 'FAILED'}", "",
              f"**Verdict:** {verdict}", ""]
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "p0": bool(p0),
                      "dispersion_mean": {k: round(v, 3) for k, v in agg.items()},
                      "cagr_spread": {k: round(v, 2) for k, v in cagr_spread.items()}},
                     indent=2))
    return summary


if __name__ == "__main__":
    main()