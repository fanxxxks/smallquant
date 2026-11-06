"""At what capital does the member-order choice stop deciding the book?

`lot_composition` (newquant/replay.py:367-412) keeps the largest prefix k whose per-member slice
clears `sleeve_floor` = max(code_gate, one board lot), then expresses `available[:k]`.  At 50 000
CNY the 10 % overseas budget (5 000) clears at k = 1, so the sleeve IS
`SLEEVE_MEMBERS["overseas"][0]` and the ordering is worth 1.74 pp/yr of terminal NAV
(run-cab8a2f4).  The handoff proposes restating the book as a specified object because "a policy
whose member order is unstated is not one object".

That inference holds only while the prefix binds, and the binding is arithmetic:

    weight * NAV / k  >=  sleeve_floor(market, available[:k], date)

so the capital at which a sleeve stops being a prefix is closed-form given that date's marks.

WHAT IS MEASURED, AND WHAT IS NOT.  Entry only, where NAV = the account's capital.  That is the
right object here: the ordering lottery is about which fund the book ends up owning, and the book
owns what entry bought.  It says nothing about returns and claims none.

PRE-DECLARED (ledger seq 192, run-ad1ffc67):

  P0 BLOCKING - the closed form at NAV = capital must equal the entry fills.  Replay the `lots`
     arm from 2016-01-04 at 50 000, 75 000 and 100 000; per sleeve, the codes bought in session 0
     must be a subset of the predicted kept set, and where the prediction is a STRICT prefix
     (k < len(available)) the bought set must equal it exactly.  Mismatch = the formula is not
     the entry rule and no frontier is quoted.

  P1 - for each of the 32 recorded quarterly starts and each capital in
     {50,60,70,80,90,100,110,120}k: can each sleeve express ALL its available members at entry?
     Plus the minimal capital C* at which it can, at every one of the 32 starts.

  DECIDE - (a) every sleeve order-free at every start by 100 000 CNY: the ordering lottery is a
     sub-100k artefact, and the handoff's spec-rewrite premise is refuted inside this account's
     own range.  (b) any sleeve still prefix-bound at 100 000: the premise survives and the
     deliverable becomes a capital threshold plus a statement of what the prefix forces.

RUNTIME NOTE - a first version of this probe (probe/expressibility_frontier.py, deleted) shrank
NAV by the deployed fraction at each re-target and reported C*_overseas = 167 739.  That model is
wrong: the unpaid residual is CASH, which is still NAV, so a re-target sees the full account plus
whatever the market did.  Nothing from it is quoted here.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from newquant.replay import (
    ARMS,
    MANDATE,
    SLEEVE_MEMBERS,
    available_members,
    build_market,
    replay,
    sleeve_floor,
    slippage_table,
)

FIRST = "2016-01-04"
END = "2026-11-04"
COST_MODE = "measured"
TOL = Decimal("15.1")
SLEEVES = ("equity", "bond", "commodity", "overseas")
CAPITALS = (50000, 60000, 70000, 80000, 90000, 100000, 110000, 120000)
P0_CAPITALS = (50000, 75000, 100000)
REF = Path("evidence/probe-retirement/summary.json")
OUT = Path("evidence/probe-expressibility")
LEDGERS = Path("/d/tmp/ef_ledgers")


def kept_at(market, sleeve: str, date: str, nav: Decimal, slippage):
    """(prefix kept, floor over all available) - replay.py:399-403 evaluated at NAV = nav."""
    available = available_members(market, sleeve, date)
    if not available or MANDATE[sleeve] <= 0:
        return (), Decimal("0")
    floor = sleeve_floor(market, available, date, TOL, slippage)
    budget = Decimal(str(MANDATE[sleeve])) * nav
    k = len(available)
    while k > 1 and budget / k < sleeve_floor(market, available[:k], date, TOL, slippage):
        k -= 1
    return available[:k], floor


def c_star(market, sleeve: str, starts, slippage) -> int | None:
    """Smallest capital that expresses every available member at every one of `starts`."""
    need = Decimal("0")
    for st in starts:
        available = available_members(market, sleeve, st)
        if len(available) < 2:
            continue
        need = max(need, sleeve_floor(market, available, st, TOL, slippage)
                   * len(available) / Decimal(str(MANDATE[sleeve])))
    return int(need.to_integral_value(rounding="ROUND_CEILING")) if need > 0 else None


def main() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    LEDGERS.mkdir(parents=True, exist_ok=True)
    starts = [row["start"] for row in json.loads(REF.read_text(encoding="utf-8"))["per_start"]]

    market = build_market("data/etf_bars.parquet", "data/corp_actions.parquet",
                          "evidence/sleeve_scores.parquet", start=FIRST, end=END)
    slippage = slippage_table(market, tuple(c for m in SLEEVE_MEMBERS.values() for c in m),
                              mode=COST_MODE)

    # ---- P0: entry closed form == entry fills -----------------------------
    p0 = {}
    for cap in P0_CAPITALS:
        res = replay(market, ARMS["lots"], nav0=Decimal(str(cap)), tolerance_bp=TOL,
                     cost_mode=COST_MODE, ledger_path=LEDGERS / f"lots__{cap}__{FIRST}.jsonl",
                     start=FIRST, end=END)
        fills = res.fills
        s0 = fills[fills["date"] == FIRST]
        bought = sorted({str(c) for c in s0["code"]})
        for sleeve in SLEEVES:
            kept, floor = kept_at(market, sleeve, FIRST, Decimal(str(cap)), slippage)
            available = available_members(market, sleeve, FIRST)
            got = [c for c in bought if c in available]
            strict = len(kept) < len(available)
            p0[f"{cap}|{sleeve}"] = {
                "available": list(available), "kept": list(kept), "bought": got,
                "strict_prefix": strict, "subset_ok": set(got) <= set(kept),
                "exact_ok": (set(got) == set(kept)) if strict else None,
                "ok": (set(got) <= set(kept)) and ((set(got) == set(kept)) if strict else True),
            }
    p0_ok = all(v["ok"] for v in p0.values())
    print(f"P0 {'ok' if p0_ok else 'FAILED'}: {sum(v['ok'] for v in p0.values())}/{len(p0)}",
          flush=True)
    for k, v in p0.items():
        if not v["ok"]:
            print("  MISMATCH", k, v, flush=True)

    if not p0_ok:
        out = {"probe": "expressibility-entry",
               "run": "run-ad1ffc67-4f30-48ef-a4f6-c02714f2350c",
               "status": "invalid_experiment: entry closed form does not reproduce entry fills",
               "p0": p0}
        (OUT / "summary.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        return out

    # ---- P1: prefix binding per sleeve per capital ------------------------
    grid: dict[str, dict[str, dict]] = {}
    for cap in CAPITALS:
        nav = Decimal(str(cap))
        grid[str(cap)] = {}
        for sleeve in SLEEVES:
            ks, bound = [], 0
            for start in starts:
                available = available_members(market, sleeve, start)
                kept, _ = kept_at(market, sleeve, start, nav, slippage)
                ks.append(len(kept))
                if len(available) > 1 and len(kept) < len(available):
                    bound += 1
            grid[str(cap)][sleeve] = {
                "n_starts": len(starts), "n_bound": bound, "share_bound": bound / len(starts),
                "k_histogram": {str(j): ks.count(j) for j in sorted(set(ks))},
            }
            print(f"[{cap:>6}] {sleeve:<9} bound {bound:>2}/{len(starts)}  "
                  f"k={grid[str(cap)][sleeve]['k_histogram']}", flush=True)

    star = {s: c_star(market, s, starts, slippage) for s in SLEEVES}
    worst = max((v for v in star.values() if v), default=None)
    inside = worst is not None and worst <= 100000
    verdict = (
        f"artefact-of-capital: every sleeve is order-free by {worst:,} CNY, inside the account's "
        "own 50-100k range" if inside else
        f"venue-constraint: the last sleeve to become order-free needs {worst:,} CNY, so the "
        "prefix rule binds across the whole 50-100k range"
    )
    out = {
        "probe": "expressibility-entry",
        "run": "run-ad1ffc67-4f30-48ef-a4f6-c02714f2350c",
        "starts": starts, "end": END, "tolerance_bp": float(TOL), "cost_mode": COST_MODE,
        "model": "entry-time only; NAV = capital, no deployment feedback",
        "p0": p0, "grid": grid,
        "c_star_per_sleeve": {k: v for k, v in star.items()},
        "c_star_all_sleeves": worst, "verdict": verdict,
    }
    (OUT / "summary.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    (OUT / "report.md").write_text(_report(out), encoding="utf-8")
    print(verdict)
    return out


def _report(s: dict) -> str:
    L = ["# Expressibility at entry: at what capital does member order stop deciding?", "",
         f"32 recorded quarterly starts, endpoint {s['end']}, tolerance {s['tolerance_bp']} bp, "
         f"cost {s['cost_mode']}, **{s['model']}**.", "",
         f"P0 entry closed form vs session-0 fills: "
         f"{sum(v['ok'] for v in s['p0'].values())}/{len(s['p0'])} agree.", "",
         "## Starts where the sleeve cannot express all its available members", "",
         "| capital | equity | bond | commodity | overseas |", "|---|---|---|---|---|"]
    for cap, sleeves in s["grid"].items():
        L.append("| " + cap + " | " + " | ".join(
            f"{sleeves[k]['n_bound']}/{sleeves[k]['n_starts']}"
            for k in ("equity", "bond", "commodity", "overseas")) + " |")
    L += ["", "## How many members the sleeve actually holds (k histogram)", "",
          "| capital | equity | bond | commodity | overseas |", "|---|---|---|---|---|"]
    for cap, sleeves in s["grid"].items():
        L.append("| " + cap + " | " + " | ".join(
            str(sleeves[k]["k_histogram"]) for k in ("equity", "bond", "commodity", "overseas"))
            + " |")
    L += ["", f"C* per sleeve: {s['c_star_per_sleeve']}",
          f"C* all sleeves: {s['c_star_all_sleeves']}", "", f"**Verdict:** {s['verdict']}.", ""]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()