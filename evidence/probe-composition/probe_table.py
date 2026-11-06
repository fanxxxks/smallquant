"""Probe: does a floor-aware static composition exist at 50k/75k/100k?

Throw-away measurement for idea v6's minimalTest. Not a module: no API, no tests.

Question: for each sleeve, what member count k can actually be *entered* at a
given NAV, over the whole 2016-2025 window, given
  (a) the post-rounding cost floor min_notional(15.1 bp, measured half tick), and
  (b) one board lot at that era's price (a slice below one lot cannot enter at all).
Kill condition: a sleeve with no feasible k at some NAV means the design's
composition cannot be static, or that sleeve cannot be held at that capital.
"""
from __future__ import annotations

import json
from decimal import Decimal

import pandas as pd

from newquant.replay import MANDATE, SLEEVE_MEMBERS, build_market, fees_for, slippage_table
from newquant.venue import min_notional

TOL = Decimal("15.1")
NAVS = (50000, 75000, 100000)
MAX_INSTRUMENTS = 6
REF = ("2016-01-04", "2020-04-07", "2023-06-01", "2025-12-31")


def main() -> int:
    market = build_market("data/etf_bars.parquet", "data/corp_actions.parquet",
                          "evidence/sleeve_scores.parquet")
    slip = slippage_table(market, tuple(c for v in SLEEVE_MEMBERS.values() for c in v), "measured")

    floor: dict[str, Decimal] = {}
    for code in slip:
        fees = fees_for(code, slip)
        m = min_notional(TOL, "buy", fees)
        floor[code] = m if m is not None else Decimal("Infinity")

    out = {"tolerance_bp": float(TOL), "navs": {}}
    print(f"{'sleeve':10s} {'code':8s} {'floor':>9s} " + " ".join(f"{d[2:7]:>8s}" for d in REF))
    for sleeve, members in SLEEVE_MEMBERS.items():
        for code in members:
            lots = []
            for d in REF:
                px = market.mark(code, d)
                lots.append(f"{float(px * 100):8.0f}" if px is not None else "     n/a")
            print(f"{sleeve:10s} {code:8s} {float(floor[code]):9.2f} " + " ".join(lots))

    for nav in NAVS:
        rows = {}
        for sleeve, members in SLEEVE_MEMBERS.items():
            w = MANDATE[sleeve]
            listed = [c for c in members if market.mark(c, REF[0]) is not None]
            candidates = []
            for k in range(1, len(members) + 1):
                slice_cny = Decimal(w) * Decimal(nav) / Decimal(k)
                need = []
                ok = True
                for code in members:
                    px = market.mark(code, REF[0])
                    if px is None:
                        continue
                    lot_cny = px * 100
                    req = max(floor[code], lot_cny)
                    if slice_cny < req:
                        ok = False
                    need.append({"code": code, "floor": float(floor[code]),
                                 "lot_cny_2016": float(lot_cny), "required": float(req)})
                candidates.append({"k": k, "slice_cny": float(slice_cny), "ok": ok,
                                   "members": need})
            best = max([c["k"] for c in candidates if c["ok"]], default=0)
            rows[sleeve] = {"weight": w, "max_feasible_k": best, "candidates": candidates}
        total = sum(r["max_feasible_k"] for r in rows.values())
        out["navs"][str(nav)] = {"sleeves": rows, "total_instruments": total,
                                 "within_cap": total <= MAX_INSTRUMENTS}
        print(f"\nNAV {nav:,}: " + "  ".join(f"{s}={r['max_feasible_k']}" for s, r in rows.items())
              + f"  total={total} cap_ok={total <= MAX_INSTRUMENTS}")
        for sleeve, r in rows.items():
            for c in r["candidates"]:
                print(f"   {sleeve:10s} k={c['k']} slice={c['slice_cny']:10.2f} ok={c['ok']}"
                      + "".join(f" [{m['code']} need {m['required']:.0f}]" for m in c["members"]))

    with open(".probe_composition.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("\nwrote .probe_composition.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
