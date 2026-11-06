"""Where does the adopted book lose to its own frozen entry book: the gate, or the trimming?

``hold-kill-single-cell`` found that freezing the entry book beats re-aiming at the mandate each
January by +14.58 % of terminal net CNY on 2016-01..2025-12 at 50 000 and 15.1 bp, with daily
vol 9.04 % vs 9.14 %.  Two candidate mechanisms, and they imply opposite fixes:

  gate  - sells are one leg at i+1 and clear easily; buys are a second leg at i+2 and each one
          is refused when the min-commission floor pushes its bp over the tolerance.  Ten years
          of that converts winners into cash: 24.79 % idle at the end vs 15.50 %.
  policy- re-aiming at 45/35/10/10 sells whatever ran.  Even with a free gate it would trim
          overseas and commodity back to 10 % every January.

The 2x2 that separates them: {15.1 bp, gate-free} x {re-aim annually, freeze}.  This probe only
measures; it decides nothing about the adopted arm, whose capital and gate are project
conditions.  Read the prints, not the code.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pandas as pd

from newquant.replay import ARMS, REPLAY_END, REPLAY_START, build_market, replay
from probe.hold_kill import daily_metrics

NAV0 = Decimal("50000")
COST_MODE = "measured"
START, END = REPLAY_START, REPLAY_END
TOLS = (Decimal("15.1"), Decimal("200"), Decimal("1000"))


def main(out_dir: str | Path = "evidence/probe-hold-kill") -> dict:
    out = Path(out_dir)
    ledger = out / "ledgers"
    ledger.mkdir(parents=True, exist_ok=True)
    market = build_market("data/etf_bars.parquet", "data/corp_actions.parquet",
                          "evidence/sleeve_scores.parquet", start=START, end=END)
    rows = {}
    monthly = {}
    for tol in TOLS:
        for arm in ("lots", "hold"):
            tag = f"{arm}@{tol}"
            path = ledger / f"nav50000_gate_{arm}_{tol}.jsonl"
            if path.exists():
                path.unlink()
            res = replay(market, ARMS[arm], nav0=NAV0, tolerance_bp=tol, cost_mode=COST_MODE,
                         ledger_path=path, start=START, end=END)
            mo = res.monthly
            monthly[tag] = mo
            rows[tag] = {
                "nav_end": float(res.stats["nav_end"]),
                "n_fills": int(res.stats["n_fills"]),
                "n_suppressed": int(len(res.suppressions)),
                "entry_invested": 1.0 - float(res.monthly.iloc[0]["cash"] / res.monthly.iloc[0]["nav"]),
                "cash_share_2025": float(mo.iloc[-1]["cash"] / mo.iloc[-1]["nav"]),
                "overseas_2025": float(mo.iloc[-1]["realised_overseas"]),
                "commodity_2025": float(mo.iloc[-1]["realised_commodity"]),
                "equity_2025": float(mo.iloc[-1]["realised_equity"]),
                "cost_bp_of_nav_per_year": float(res.stats["cost_bp_of_nav_per_year"]),
                **daily_metrics(res.daily, NAV0),
            }
    # the two readings the pre-declared rule turns on
    verdicts = {}
    for tol in TOLS[1:]:
        lots, hold = rows[f"lots@{tol}"], rows[f"hold@{tol}"]
        ratio = lots["nav_end"] / hold["nav_end"]
        verdicts[f"tol{tol}"] = {
            "lots_over_hold": ratio,
            "gap_pct": (ratio - 1.0) * 100.0,
            "gate_free": rows[f"lots@{tol}"]["n_suppressed"] == 0
                         and rows[f"hold@{tol}"]["n_suppressed"] == 0,
            "reading": ("gate is the binding constraint; maintenance neutral when the gate does "
                        "not bind" if abs(ratio - 1.0) <= 0.02 else
                        "maintenance beats freezing even with a free gate" if ratio > 1.02 else
                        "trimming destroys value at both gate levels"),
        }
    summary = {"probe": "open-gate-decomposition", "window": {"start": START, "end": END},
               "cell": {"nav0": float(NAV0), "cost_mode": COST_MODE,
                        "tolerances": [float(t) for t in TOLS]},
               "arms": rows, "verdicts": verdicts}
    (out / "gate-decomp.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                          encoding="utf-8")
    return summary


if __name__ == "__main__":
    s = main()
    print(f"{'arm':12s} {'nav_end':>12s} {'fills':>6s} {'suppr':>6s} {'inv%':>6s} {'cash%':>7s} "
          f"{'os%':>6s} {'cm%':>6s} {'mdd':>8s} {'vol':>7s} {'costbp':>7s}")
    for k, v in s["arms"].items():
        print(f"{k:12s} {v['nav_end']:12,.2f} {v['n_fills']:6d} {v['n_suppressed']:6d} "
              f"{v['entry_invested']:6.1%} {v['cash_share_2025']:7.2%} {v['overseas_2025']:6.2%} "
              f"{v['commodity_2025']:6.2%} {v['max_drawdown_daily']:8.2%} {v['vol_annual_252']:7.2%} "
              f"{v['cost_bp_of_nav_per_year']:7.2f}")
    print(json.dumps(s["verdicts"], indent=2, ensure_ascii=False))