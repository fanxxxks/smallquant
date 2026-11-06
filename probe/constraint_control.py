"""Is the ordering spread the board lot, the cost gate, or neither?

Direction review round round-6f4b2aac put two blockers on `member-count-frontier`:

  R2  the 1.743 pp/yr spread across overseas orderings may measure alternative exposures
      rather than a trading constraint, so a constrained-vs-relaxed control is required.
  R1  the entry-time closed form was validated at entry only; the holding-count law has to be
      shown on the path, with existing positions and suppressed incremental orders included.

The gate is enforced TWICE - in `sleeve_floor` before the member count is chosen
(newquant/replay.py:363 via code_gate) and again on the final post-rounding notional when the
order is routed (newquant/order.py:84 `gate_ok`).  Relaxing only the first leaves a composition
the second refuses: measured on 2016-01-04, floor=lot-only keeps all three overseas members at
0.0962 combined weight and the replay then fills none of them for ten years.  So the gate is
relaxed with the engine's own knob (`tolerance_bp`) and only the lot term is patched:

  base      tol 15.1 bp, floor = max(gate, one lot)          as shipped
  gate_off  tol 1e6 bp,  floor = one lot (gate term is 0)    no cost gate anywhere
  lot_off   tol 15.1 bp, floor = gate only                   board lot ignored in the choice
  free      tol 1e6 bp,  floor = 0                           neither constraint

Orders still round to whole lots in every regime, so `free` removes the lot from the member-count
decision only, not from the arithmetic.

PRE-DECLARED (before any number from this script):
  P0 base regime reproduces the recorded 50k grid's six ordering means to +-0.01 pp against
     hold@200; else invalid_experiment and nothing is quotable.
  P1 dispersion across the six orderings of terminal NAV, within each regime, as (max-min)/mean
     in per-cent, averaged over the six starts.
  DECIDE (a) dispersion(free) <= 0.2*base and dispersion(lot_off) >= 0.7*base and
     dispersion(gate_off) <= 0.3*base -> the COST GATE is the lever; (b) the mirror -> the BOARD
     LOT is the lever; (c) dispersion(free) > 0.2*base -> the dispersion is not constraint-caused
     at all, which kills the direction; (d) otherwise the two do not separate and R2 stays open.
  P2 path check, base regime: on every monthly row that carries a fill, compare the engine's
     members_overseas with the closed form k = max{k : 0.10*nav/k >= floor(available[:k])}.
     Reported as an agreement rate, not as pass/fail.
"""

from __future__ import annotations

import itertools
import json
from decimal import Decimal
from pathlib import Path

import pandas as pd

import newquant.replay as rp
from newquant.replay import ARMS, MANDATE, build_market, replay, slippage_table, TRADED

NAV0 = Decimal("50000")
COST_MODE = "measured"
FIRST, END = "2016-01-04", "2026-11-04"
STARTS = ("2016-01-04", "2017-04-05", "2018-07-02",
          "2020-01-02", "2021-10-08", "2023-10-09")
BASE = ("513100", "513500", "159920")
TOL = Decimal("15.1")
WIDE = Decimal("1000000")  # 1e6 bp = 10 000 %: no order can fail the gate
REGIMES = (("base", TOL, True), ("gate_off", WIDE, True),
           ("lot_off", TOL, False), ("free", WIDE, False))
OUT = Path("evidence/probe-constraint-control")
LEDGERS = Path("/tmp/rd_cc")
RECORDED = Path("evidence/probe-member-order/summary.json")

ORIG_FLOOR = rp.sleeve_floor


def floor_gate_only(market, codes, date, tol, slippage):
    """sleeve_floor with the board-lot term dropped: max over codes of the cost gate alone."""
    need = Decimal("0")
    for code in codes:
        if market.mark(code, date) is None:
            continue
        need = max(need, rp.code_gate(code, tol, slippage))
    return need


def closed_form_k(market, nav: Decimal, date: str, slippage) -> int:
    available = rp.available_members(market, "overseas", date)
    if not available:
        return 0
    budget = Decimal(str(MANDATE["overseas"])) * nav
    k = len(available)
    while k > 1 and budget / k < ORIG_FLOOR(market, available[:k], date, TOL, slippage):
        k -= 1
    return k


def path_check(market, res, slippage) -> dict:
    mon = res.monthly
    fill_months = {str(d)[:7] for d in res.fills["date"]} if len(res.fills) else set()
    rows, agree, checked = [], 0, 0
    for _, row in mon.iterrows():
        date = str(row["date"])[:10]
        engine_k = int(row.get("members_overseas") or 0)
        if date[:7] not in fill_months:
            rows.append({"date": date, "engine_k": engine_k, "closed_k": None})
            continue
        closed = closed_form_k(market, Decimal(str(row["nav"])), date, slippage)
        checked += 1
        agree += int(closed == engine_k)
        rows.append({"date": date, "engine_k": engine_k, "closed_k": closed,
                     "nav": float(row["nav"])})
    return {"rows": rows, "checked": checked, "agree": agree}


def main() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    LEDGERS.mkdir(parents=True, exist_ok=True)
    market = build_market("data/etf_bars.parquet", "data/corp_actions.parquet",
                          "evidence/sleeve_scores.parquet", start=FIRST, end=END)
    slippage = slippage_table(market, TRADED, mode=COST_MODE)
    recorded = json.loads(RECORDED.read_text(encoding="utf-8"))
    ref = {p["tag"]: p["gap_mean_pp"] for p in recorded["per_order"]}

    orderings = list(itertools.permutations(BASE))
    original_members = rp.SLEEVE_MEMBERS["overseas"]
    hold: dict[str, float] = {}
    years: dict[str, float] = {}
    cells: dict[str, dict[str, dict]] = {}
    paths: dict[str, dict] = {}

    try:
        rp.SLEEVE_MEMBERS["overseas"] = BASE
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
                rp.SLEEVE_MEMBERS["overseas"] = order
                tag = "-".join(order)
                cells[regime][tag] = {}
                for start in STARTS:
                    res = replay(market, ARMS["lots"], nav0=NAV0, tolerance_bp=tol,
                                 cost_mode=COST_MODE,
                                 ledger_path=LEDGERS / f"{regime}__{tag}__{start}.jsonl",
                                 start=start, end=END)
                    nav = float(res.stats["nav_end"])
                    gap = ((hold[start] / nav) ** (1.0 / years[start]) - 1.0) * 100.0
                    cells[regime][tag][start] = {
                        "nav_end": nav, "gap_pp_yr": gap,
                        "ovs_end": float(res.monthly.iloc[-1]["realised_overseas"])}
                    if regime == "base" and tag == "-".join(BASE):
                        paths[start] = path_check(market, res, slippage)
                mean_gap = sum(cells[regime][tag][s]["gap_pp_yr"] for s in STARTS) / len(STARTS)
                print(f"[{regime}] {tag}  mean gap {mean_gap:+.3f} pp/yr", flush=True)
    finally:
        rp.sleeve_floor = ORIG_FLOOR
        rp.SLEEVE_MEMBERS["overseas"] = original_members

    base_means = {t: sum(cells["base"][t][s]["gap_pp_yr"] for s in STARTS) / len(STARTS)
                  for t in cells["base"]}
    p0 = {t: abs(base_means[t] - ref[t]) for t in base_means if t in ref}
    p0_max = max(p0.values()) if p0 else 99.0
    summary: dict = {"probe": "constraint-control", "nav0": float(NAV0),
                     "starts": list(STARTS),
                     "p0": {"max_abs_diff_pp": p0_max, "per_order": p0,
                            "ok": p0_max <= 0.011 and len(p0) == 6}}
    if not summary["p0"]["ok"]:
        summary["verdict"] = "invalid_experiment: base regime does not reproduce the recorded grid"
        (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    disp, per_regime = {}, {}
    for regime, _, _ in REGIMES:
        per_start = {}
        for start in STARTS:
            navs = [cells[regime][t][start]["nav_end"] for t in cells[regime]]
            per_start[start] = (max(navs) - min(navs)) / (sum(navs) / len(navs)) * 100.0
        means = {t: sum(cells[regime][t][s]["gap_pp_yr"] for s in STARTS) / len(STARTS)
                 for t in cells[regime]}
        disp[regime] = sum(per_start.values()) / len(per_start)
        per_regime[regime] = {
            "dispersion_pct": disp[regime], "per_start_pct": per_start,
            "order_means_pp": means,
            "spread_pp": max(means.values()) - min(means.values()),
            "ovs_end_by_order": {t: [round(cells[regime][t][s]["ovs_end"], 4) for s in STARTS]
                                 for t in cells[regime]}}

    b = disp["base"]
    if disp["free"] <= 0.2 * b and disp["lot_off"] >= 0.7 * b and disp["gate_off"] <= 0.3 * b:
        verdict = "cost-gate-is-the-lever"
    elif disp["free"] <= 0.2 * b and disp["gate_off"] >= 0.7 * b and disp["lot_off"] <= 0.3 * b:
        verdict = "board-lot-is-the-lever"
    elif disp["free"] > 0.2 * b:
        verdict = ("dispersion-is-not-constraint: the orderings still disperse with no floor at "
                   "all, so the direction fails its own kill test")
    else:
        verdict = "both-terms-contribute: the two constraints do not separate in this window"

    agree = sum(p["agree"] for p in paths.values())
    checked = sum(p["checked"] for p in paths.values())
    summary.update({"dispersion_pct": disp, "per_regime": per_regime, "verdict": verdict,
                    "path_check": {"checked": checked, "agree": agree,
                                   "agreement": (agree / checked) if checked else None},
                    "cells": cells, "paths": paths})
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = ["# Constraint control: board lot, cost gate, or neither?", "",
             f"50 000 CNY, {len(STARTS)} starts, six overseas orderings, four regimes.",
             f"P0: base regime reproduces the recorded grid to {p0_max:.4f} pp.", "",
             "| regime | dispersion across orderings (%) | ratio to base |",
             "|---|---|---|"]
    for regime, _, _ in REGIMES:
        lines.append(f"| {regime} | {disp[regime]:.3f} | {disp[regime] / b:.2f} x |")
    lines += ["", f"**Verdict:** {verdict}", "",
              f"Path check (base regime, fill rows): closed form matches the engine's member "
              f"count on {agree}/{checked} rows.", ""]
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"verdict": verdict,
                      "dispersion": {k: round(v, 3) for k, v in disp.items()},
                      "p0": p0_max, "path": f"{agree}/{checked}"}, indent=2))
    return summary


if __name__ == "__main__":
    main()