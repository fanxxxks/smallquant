"""Probe 2: what weight can the frozen venue actually express at entry?

Same throw-away rules as .probe_composition.py. Uses the smallest feasible static
composition found by probe 1: equity (510300, 510500), bond (511220),
commodity (518880), overseas (513100).
"""
from __future__ import annotations
from decimal import Decimal
import pandas as pd
from newquant.replay import MANDATE, build_market

COMPOSITION = {"equity": ("510300", "510500"), "bond": ("511220",),
               "commodity": ("518880",), "overseas": ("513100",)}
NAVS = (50000, 75000, 100000)
REF = {"2016-01-04": "2016-2022 (pre-split)", "2020-04-07": "2020",
       "2023-06-01": "2023+ (post 10:1 split)"}

market = build_market("data/etf_bars.parquet", "data/corp_actions.parquet",
                      "evidence/sleeve_scores.parquet")
print(f"{'date':8s} {'sleeve':10s} {'target':>7s} {'aimed':>9s} {'bought':>9s} "
      f"{'realised':>9s} {'gap_pp':>7s}  lots")
for d, label in REF.items():
    for nav in NAVS:
        tot_real = Decimal(0)
        rows = []
        for sleeve, members in COMPOSITION.items():
            w = Decimal(str(MANDATE[sleeve]))
            aimed = w * nav / len(members)
            got = Decimal(0)
            lots_txt = []
            for code in members:
                px = market.mark(code, d)
                lot = px * 100
                n = int((aimed / lot).to_integral_value(rounding="ROUND_FLOOR"))
                got += n * lot
                lots_txt.append(f"{code}:{n}")
            tot_real += got
            rows.append((sleeve, w * nav, aimed * len(members), got,
                         (got / nav - w) * 100, " ".join(lots_txt)))
        for sleeve, target, aimed_total, got, gap, lots_txt in rows:
            print(f"{d[2:]:8s} {sleeve:10s} {float(target):7.0f} {float(aimed_total):9.0f} "
                  f"{float(got):9.0f} {float(got/nav)*100:8.1f}% {float(gap):+7.1f}  {lots_txt}")
        invested = tot_real / nav
        print(f"{'':8s} {'TOTAL':10s} {'':7s} {'':9s} {float(tot_real):9.0f} "
              f"{float(invested)*100:8.1f}% {float((invested-Decimal("0.9"))*100):+7.1f}  cash {(1-float(invested))*100:.1f}%")
    print()
