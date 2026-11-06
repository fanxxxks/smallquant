"""Probe: is E3's lots-static uplift the lot rule, or just the two sleeves E2 never held?

Disposable. One question: on the frozen venue, with the removed sleeve's weight left in cash
and no renormalisation of the others, how much of the +1,542.8 CNY/yr survives?

Declared before the run (see ledger run-db12778c):
  * retain the composition claim only if no_both >= 60 % of full (~925 CNY/yr) with an
    interval excluding zero;
  * narrow it to "hold every sleeve with one lot" if no_both < 30 % (~463) or its
    interval includes zero.
"""

from __future__ import annotations

import json
import math
import time
from decimal import Decimal
from pathlib import Path

import pandas as pd

from newquant import replay as R
from newquant.eval.e2 import Cell, _cny_block, _delta_series
from newquant.eval.e3 import BARS, CORP, SCORES, run_cell

OUT = Path("evidence/probe-ablation")
BASE = dict(R.MANDATE)
VARIANTS = {
    "full": {},
    "no_commodity": {"commodity": 0.0},
    "no_overseas": {"overseas": 0.0},
    "no_both": {"commodity": 0.0, "overseas": 0.0},
    "no_bond": {"bond": 0.0},
}
CAPITAL_CELLS = (Decimal(75000), Decimal(100000))
TOL = Decimal("15.1")
KEEP = ("nav_end", "cagr", "vol_annual", "max_drawdown", "cost_bp_of_nav_per_year",
        "n_fills", "n_intents", "suppressed", "mean_tracking_error")


def _slim(arm: dict) -> dict:
    out = {k: arm.get(k) for k in KEEP}
    entry = arm.get("entry") or {}
    out["entry"] = {k: entry.get(k) for k in
                    ("invested", "cash", "equity", "bond", "commodity", "overseas")}
    return out


def _block(delta: pd.Series) -> dict:
    b = _cny_block(delta)
    return {k: b[k] for k in ("annual_cny", "annual_cny_lo", "annual_cny_hi", "cumulative_cny",
                              "sd_monthly_cny", "mde_annual_cny")}


def main() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ledgers").mkdir(exist_ok=True)
    market = R.build_market(BARS, CORP, SCORES)
    started = time.time()
    summary: dict = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                     "base_mandate": BASE, "variants": {}, "subsample_mde": {}}
    nav0 = Decimal(50000)

    try:
        for name, override in VARIANTS.items():
            R.MANDATE.clear()
            R.MANDATE.update({**BASE, **override})
            cell = Cell(nav0, TOL, "measured")
            res = run_cell(market, cell, ledger_dir=OUT / "ledgers",
                           arms=("static", "lots"))
            delta = _delta_series(res["monthly"]["static"], res["monthly"]["lots"], nav0)
            summary["variants"][name] = {
                "mandate": dict(R.MANDATE),
                "arms": {a: _slim(b) for a, b in res["arms"].items()},
                "lots_minus_static": _block(delta),
                "seconds": res["seconds"],
            }
            if name == "full":
                for tag, chunk in (("first_60m", delta.iloc[:60]),
                                   ("last_60m", delta.iloc[-60:]),
                                   ("middle_2000_2022", delta.iloc[60:120])):
                    summary["subsample_mde"][tag] = _block(chunk)
                summary["monthly_delta_full"] = {d: float(v) for d, v in delta.items()}

        for nav in CAPITAL_CELLS:
            for name in ("full", "no_both"):
                R.MANDATE.clear()
                R.MANDATE.update({**BASE, **VARIANTS[name]})
                cell = Cell(nav, TOL, "measured")
                res = run_cell(market, cell, ledger_dir=OUT / "ledgers",
                               arms=("static", "lots"))
                delta = _delta_series(res["monthly"]["static"], res["monthly"]["lots"], nav)
                summary.setdefault("capital", {})[f"nav{int(nav)}_{name}"] = {
                    "arms": {a: {"nav_end": b["nav_end"], "cagr": b["cagr"],
                                 "n_fills": b["n_fills"]} for a, b in res["arms"].items()},
                    "lots_minus_static": _block(delta),
                }
    finally:
        R.MANDATE.clear()
        R.MANDATE.update(BASE)

    summary["seconds"] = round(time.time() - started, 1)
    full = summary["variants"]["full"]["lots_minus_static"]["annual_cny"]
    for name, block in summary["variants"].items():
        block["share_of_full"] = (block["lots_minus_static"]["annual_cny"] / full
                                  if math.isfinite(full) and full else float("nan"))
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=str),
                                      encoding="utf-8")
    return summary


if __name__ == "__main__":
    s = main()
    print(json.dumps({n: {"delta": round(v["lots_minus_static"]["annual_cny"], 1),
                          "lo": round(v["lots_minus_static"]["annual_cny_lo"], 1),
                          "hi": round(v["lots_minus_static"]["annual_cny_hi"], 1),
                          "mde": round(v["lots_minus_static"]["mde_annual_cny"], 1),
                          "share": round(v["share_of_full"], 3) if isinstance(
                              v["share_of_full"], float) else v["share_of_full"],
                          "nav_end": {a: round(b["nav_end"], 2) for a, b in v["arms"].items()},
                          "fills": {a: b["n_fills"] for a, b in v["arms"].items()}}
                      for n, v in s["variants"].items()}
                 | {"subsample_mde": {k: round(v["mde_annual_cny"], 1)
                                      for k, v in s["subsample_mde"].items()},
                    "capital": {k: round(v["lots_minus_static"]["annual_cny"], 1)
                                for k, v in s.get("capital", {}).items()},
                    "seconds": s["seconds"]}, indent=1))
