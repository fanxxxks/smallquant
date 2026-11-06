"""Is the construction's edge a rule, or the member that happens to sort first?

`lot_composition` shrinks a sleeve to the largest prefix whose per-member slice clears
`max(min_notional, one board lot)` and keeps `available[:k]` (newquant/replay.py:401,403).  At
50 000 CNY the 10 % overseas budget (5 000) clears that floor only at k = 1, so the sleeve is not
equal-weighted and not chosen by any stated criterion - it is `SLEEVE_MEMBERS["overseas"][0]`.
In this window that code was 513100 (qfq CAGR 19.77 %) and the members it displaced were 513500
(13.42 %) and 159920 (1.12 %).

The naive `hold` arm buys every available member, so it is order-invariant apart from rounding
ties.  That asymmetry is what makes this a test: permute the overseas tuple and the naive arm
should barely move while the adopted book moves a lot.  If the paired gap survives every
ordering, the edge is a mechanism; if it follows the ordering, the edge is the prefix rule
landing on the window's winner.

PRE-DECLARED (ledger seq 183, run-cab8a2f4, before any number from this script):
  P0 reproduction, BLOCKING - the identity ordering (513100,513500,159920) must reproduce
     run-39aad9d7 at all 6 starts for BOTH arms to +-0.01 CNY, else the monkeypatch is not
     equivalent and no permutation quotes.
  P1 per ordering, paired annualised gap hold@200 - lots@15.1 over the 6 starts.
  DECIDE - any ordering with a mean gap > 0, or a mean across orderings inside [-0.6, 0] pp,
     means the edge is order-dependent (the artifact reading stands).  All six ordering means
     <= -0.6 pp means the edge is not order-driven and residual-cash deployment is the
     candidate mechanism instead.
This is attribution on windows run-5a92eb45 already read; it decides nothing about new returns.
"""

from __future__ import annotations

import argparse
import itertools
import json
from decimal import Decimal
from pathlib import Path

import newquant.replay as rp
from newquant.replay import ARMS, build_market, replay
from probe.hold_kill import daily_metrics

NAV0 = Decimal("50000")
REF_NAV = Decimal("50000")  # the recorded reference exists only at this capital
COST_MODE = "measured"
FIRST = "2016-01-04"
END = "2026-11-04"

OUT = Path("evidence/probe-member-order")
LEDGERS = Path("/tmp/rd_perm")
RECORDED = Path("evidence/probe-retirement/summary.json")

BASE_OVERSEAS = ("513100", "513500", "159920")
STARTS = ("2016-01-04", "2017-04-05", "2018-07-02",
          "2020-01-02", "2021-10-08", "2023-10-09")
ARMS_UNDER_TEST = (("lots@15.1", "lots", Decimal("15.1")),
                   ("hold@200", "hold", Decimal("200")))
IDENTITY = BASE_OVERSEAS


def perm_tag(order: tuple[str, ...]) -> str:
    return "-".join(order)


def run_cell(market, arm: str, tol: Decimal, start: str, tag: str,
             nav0: Decimal = NAV0, ledgers: Path = LEDGERS) -> dict:
    path = ledgers / f"{tag}__{start}.jsonl"
    res = replay(market, ARMS[arm], nav0=nav0, tolerance_bp=tol, cost_mode=COST_MODE,
                 ledger_path=path, start=start, end=END)
    last = res.monthly.iloc[-1]
    first = res.monthly.iloc[0]
    bought = {}
    for _, fill in res.fills.iterrows():
        code = fill["code"]
        if code in BASE_OVERSEAS and fill["side"] == "buy":
            bought[code] = bought.get(code, 0.0) + float(fill["notional"])
    return {
        "nav_end": float(res.stats["nav_end"]),
        "n_fills": int(res.stats["n_fills"]),
        "entry_cash_share": float(first["cash"] / first["nav"]),
        "cash_end_share": float(last["cash"] / last["nav"]),
        "realised_overseas_end": float(last["realised_overseas"]),
        "overseas_bought_cny": bought,
        "cost_bp_of_nav_per_year": float(res.stats["cost_bp_of_nav_per_year"]),
        **daily_metrics(res.daily, NAV0),
    }


def main(check_only: bool = False, nav0: Decimal = NAV0, outdir: Path = OUT,
         ledgers: Path = LEDGERS) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    ledgers.mkdir(parents=True, exist_ok=True)
    recorded = json.loads(RECORDED.read_text(encoding="utf-8"))
    ref = {}
    for row in recorded["per_start"]:
        ref.setdefault(row["start"], {})["lots@15.1"] = row["lots_nav"]
        ref.setdefault(row["start"], {})["hold@200"] = row["hold200_nav"]

    market = build_market("data/etf_bars.parquet", "data/corp_actions.parquet",
                          "evidence/sleeve_scores.parquet", start=FIRST, end=END)
    original = rp.SLEEVE_MEMBERS["overseas"]
    orderings = list(itertools.permutations(BASE_OVERSEAS))
    if check_only:
        orderings = [IDENTITY]

    cells: dict[str, dict[str, dict]] = {}
    try:
        for order in orderings:
            rp.SLEEVE_MEMBERS["overseas"] = order
            tag = perm_tag(order)
            cells[tag] = {}
            for start in STARTS:
                for arm_tag, arm, tol in ARMS_UNDER_TEST:
                    cells[tag].setdefault(start, {})[arm_tag] = run_cell(
                        market, arm, tol, start, f"{tag}__{arm_tag.replace('.', '_')}",
                        nav0=nav0, ledgers=ledgers)
                c = cells[tag][start]
                print(f"[{tag}] {start}  lots={c['lots@15.1']['nav_end']:,.0f}"
                      f"  hold200={c['hold@200']['nav_end']:,.0f}"
                      f"  ovs_lots={c['lots@15.1']['realised_overseas_end']:.3f}",
                      flush=True)
    finally:
        rp.SLEEVE_MEMBERS["overseas"] = original

    # ---- P0: is the identity ordering the same experiment as seq 181? -------
    ident = perm_tag(IDENTITY)
    p0 = {}
    for start in STARTS:
        for arm_tag, _, _ in ARMS_UNDER_TEST:
            got = cells[ident][start][arm_tag]["nav_end"]
            want = ref[start][arm_tag]
            p0[f"{start}|{arm_tag}"] = abs(got - want)
    p0_max = max(p0.values())
    anchored = nav0 == REF_NAV
    repro = {"max_abs_diff_cny": p0_max, "ok": (p0_max <= 0.011) or not anchored,
             "per_cell": p0, "anchored": anchored}

    if check_only:
        out = {"probe": "member-order-permutation", "mode": "check", "reproduction": repro,
               "cells": cells}
        (OUT / "check.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(json.dumps({"check": repro["ok"], "max_abs_diff_cny": p0_max}))
        return out

    if not repro["ok"]:
        out = {"probe": "member-order-permutation", "reproduction": repro,
               "verdict": "invalid_experiment: identity ordering does not reproduce seq 181"}
        (OUT / "summary.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        return out

    # ---- P1: paired gap per ordering ---------------------------------------
    per_order = []
    for order in orderings:
        tag = perm_tag(order)
        gaps, pairs = [], []
        for start in STARTS:
            b = cells[tag][start]["lots@15.1"]
            h = cells[tag][start]["hold@200"]
            years = b["years_calendar"]
            gap = ((h["nav_end"] / b["nav_end"]) ** (1.0 / years) - 1.0) * 100.0
            gaps.append(gap)
            pairs.append({"start": start, "years": years,
                          "lots_nav": b["nav_end"], "hold200_nav": h["nav_end"],
                          "ratio": h["nav_end"] / b["nav_end"], "gap_pp_yr": gap,
                          "overseas_first_bought": next(
                              (c for c in order
                               if b["overseas_bought_cny"].get(c, 0) > 0), None),
                          "overseas_members_bought": sorted(b["overseas_bought_cny"]),
                          "lots_overseas_end": b["realised_overseas_end"],
                          "hold_overseas_end": h["realised_overseas_end"]})
        mean = sum(gaps) / len(gaps)
        per_order.append({"order": list(order), "tag": tag,
                          "gap_mean_pp": mean, "gap_min_pp": min(gaps),
                          "gap_max_pp": max(gaps),
                          "n_hold_ahead": int(sum(1 for g in gaps if g > 0)),
                          "pairs": pairs})

    order_means = [o["gap_mean_pp"] for o in per_order]
    grand = sum(order_means) / len(order_means)
    any_ahead = any(m > 0 for m in order_means)
    inside_band = -0.6 < grand <= 0
    verdict = ("order-dependent: the edge follows the member tuple"
               if (any_ahead or inside_band)
               else "not order-driven: all orderings keep the simpler policy >= -0.6 pp behind")

    out = {"probe": "member-order-permutation",
           "run": "run-cab8a2f4-fdf3-4570-9070-6276c1b02284",
           "starts": list(STARTS), "end": END, "nav0": float(nav0),
           "reproduction": repro,
           "per_order": per_order,
           "summary": {"order_means_pp": order_means,
                       "grand_mean_pp": grand,
                       "spread_pp": max(order_means) - min(order_means),
                       "any_ordering_puts_simple_ahead": any_ahead,
                       "grand_mean_inside_band": inside_band,
                       "verdict": verdict}}
    (outdir / "summary.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    (outdir / "report.md").write_text(_report(out), encoding="utf-8")
    print(verdict)
    return out


def _report(s: dict) -> str:
    lines = ["# Overseas member order: rule or lottery?", "",
             f"6 orderings x {len(s['starts'])} starts x 2 arms, NAV0 50 000, cost measured, "
             f"endpoint {s['end']}.", "",
             f"P0 reproduction max |diff| = {s['reproduction']['max_abs_diff_cny']:.2f} CNY "
             f"({'ok' if s['reproduction']['ok'] else 'FAILED'}).", "",
             "| overseas order | mean gap pp/yr | min | max | hold ahead |",
             "|---|---|---|---|---|"]
    for o in s["per_order"]:
        lines.append(f"| {o['tag']} | {o['gap_mean_pp']:+.3f} | {o['gap_min_pp']:+.3f} "
                     f"| {o['gap_max_pp']:+.3f} | {o['n_hold_ahead']}/6 |")
    sm = s["summary"]
    lines += ["", f"Grand mean {sm['grand_mean_pp']:+.3f} pp/yr, "
                  f"spread across orderings {sm['spread_pp']:.3f} pp.", "",
              f"**Verdict:** {sm['verdict']}.", "",
              "## Per-cell detail", "",
              "| order | start | lots nav | hold200 nav | ratio | gap pp/yr | overseas first bought |",
              "|---|---|---|---|---|---|---|"]
    for o in s["per_order"]:
        for p in o["pairs"]:
            lines.append(f"| {o['tag']} | {p['start']} | {p['lots_nav']:,.0f} "
                         f"| {p['hold200_nav']:,.0f} | {p['ratio']:.4f} | {p['gap_pp_yr']:+.3f} "
                         f"| {p['overseas_first_bought']} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--nav", type=float, default=50000.0)
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    nav = Decimal(str(args.nav))
    suf = args.tag or ("" if nav == REF_NAV else f"-nav{int(nav)}")
    main(check_only=args.check, nav0=nav,
         outdir=Path(f"evidence/probe-member-order{suf}"),
         ledgers=Path(f"/d/tmp/rd_perm{suf}"))