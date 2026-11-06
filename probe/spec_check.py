"""Run the proposed specification exactly as an account would hold it.

SLEEVE_MEMBERS becomes one NAMED fund per sleeve: overseas ('513100',), commodity ('518880',),
bond and equity keep their members because they express fully at 50 000 CNY.  A one-member
tuple has no ordering, so this must reproduce the 513100-first cell of the dispersion grid
exactly; anything else is a routing artefact.

PRE-DECLARED: P0 every start's terminal NAV must equal
evidence/probe-sleeve-dispersion/summary.json terminal_nav['overseas'][start]['513100-513500-159920']
to 0.01 CNY.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import newquant.replay as rp
from newquant.replay import ARMS, replay, build_market

NAV0 = Decimal("50000")
FIRST, END = "2016-01-04", "2026-11-04"
STARTS = ("2016-01-04", "2017-04-05", "2018-07-02",
          "2020-01-02", "2021-10-08", "2023-10-09")
SPEC = {"equity": ("510300", "510500", "512100"), "bond": ("511220", "511380"),
        "commodity": ("518880",), "overseas": ("513100",)}
OUT = Path("evidence/probe-spec-check")
REF = json.loads(Path("evidence/probe-sleeve-dispersion/summary.json").read_text(encoding="utf-8"))

original = dict(rp.SLEEVE_MEMBERS)
try:
    rp.SLEEVE_MEMBERS.update(SPEC)
    market = build_market("data/etf_bars.parquet", "data/corp_actions.parquet",
                          "evidence/sleeve_scores.parquet", start=FIRST, end=END)
    rows = {}
    for start in STARTS:
        res = replay(market, ARMS["lots"], nav0=NAV0, tolerance_bp=Decimal("15.1"),
                     cost_mode="measured", ledger_path=Path("/d/tmp/rd_spec") / f"spec__{start}.jsonl",
                     start=start, end=END)
        nav = float(res.stats["nav_end"])
        ref = REF["terminal_nav"]["overseas"][start]["513100-513500-159920"]
        last = res.monthly.iloc[-1]
        rows[start] = {"nav_end": nav, "ref_513100_first": ref, "diff": round(nav - ref, 4),
                       "w_equity": float(last["realised_equity"]),
                       "w_bond": float(last["realised_bond"]),
                       "w_commodity": float(last["realised_commodity"]),
                       "w_overseas": float(last["realised_overseas"]),
                       "cost_bp": float(res.stats.get("cost_bp", 0.0))}
        print(f"{start} spec {nav:12.2f} vs 513100-first {nav - ref:+8.2f} "
              f"weights e{rows[start]['w_equity']:.3f} b{rows[start]['w_bond']:.3f} "
              f"c{rows[start]['w_commodity']:.3f} o{rows[start]['w_overseas']:.3f}", flush=True)
finally:
    for k, v in original.items():
        rp.SLEEVE_MEMBERS[k] = v

p0 = all(abs(r["diff"]) <= 0.01 for r in rows.values())
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "summary.json").write_text(json.dumps(
    {"probe": "spec-check", "nav0": float(NAV0), "sleeve_members": SPEC, "rows": rows,
     "p0_ok": p0,
     "verdict": "spec-reproduces-513100-first" if p0 else "routing-artefact"}, indent=2),
    encoding="utf-8")
print(json.dumps({"p0_ok": p0, "navs": {k: round(v["nav_end"], 2) for k, v in rows.items()},
                  "verdict": "spec-reproduces-513100-first" if p0 else "routing-artefact"}, indent=2))
