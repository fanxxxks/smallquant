"""Where the maintenance side stops being inert: measure the capital frontier instead of guessing.

Confirm-step artefact for ledger seq 124 (`gate-binds-maintenance-not-entry`), which showed the
entry clears every sleeve at 50,000 CNY while 46 of 57 maintenance intents sit below a bound that
does not move with price. The extrapolation on record (handoff seq 127, next item 2) is that the
maintenance median crosses the clearing bound near 250,000-300,000 CNY, read from two points:
median intent 1,888.5 at 50,000 and 2,490.1 at 120,000 for 2.4x the capital. Two points do not make
a curve, and the 120,000 ledgers may not even come from the same configuration.

This probe runs the same cell at 200,000 and 250,000 through ``e3.run_cell`` - the audited path,
all arms, nothing reimplemented - and reports, per cell: the intent population and its
below-clearing share in the build and maintenance regimes separately, the median intent against the
clearing bound, the entry composition and its gaps in percentage points, the post-entry fill count
and cost. Ledgers land in evidence/probe-capital-ladder/ledgers.

Pre-declared rule (recorded with the run before it executed):
  C1 if the maintenance below-clearing share at 200,000 is still >= 0.75, capital is not the knob;
     seq 124's 'capital is the only knob that improves both ends' is refuted at that level and the
     frontier claim is withdrawn rather than moved.
  C2 if the share falls 0.807 -> below 0.60 by 250,000 AND the median maintenance intent crosses
     the 3,669.17 CNY clearing median, the frontier is measured: state it as the capital at which
     the median delta clears, with the crossing cell named.
  C3 if the share falls but the post-entry fill count does not rise, the mechanism is not clearing -
     it is a change in what the book holds (member counts, sleeve weights) - and the finding must be
     restated as a composition effect, not a gate effect.

Run: PYTHONPATH=. python probe/capital_ladder.py
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from newquant.eval import e3
from newquant.eval.e2 import Cell
from newquant.ledger import LedgerStore
from newquant.replay import MANDATE, build_market

from probe.below_clearing_era import clearing_table, intents, sleeve_map, summarise

OUT = Path("evidence/probe-capital-ladder")
NAVS = (Decimal(120000), Decimal(200000), Decimal(250000))
TOLERANCE = Decimal("15.1")
COST_MODE = "measured"
SLEEVES = ("equity", "bond", "commodity", "overseas")
# The 50,000 reference, from evidence/probe-below-clearing-era/summary.json (seq 122).
REF_50K = {"maintenance_below_share": 0.8070, "maintenance_median_cny": 1659.6,
           "maintenance_fills": 9, "pooled_below_share": 0.7538, "pooled_median_cny": 1888.5}


def split(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Session 0 is the build (seq 115): everything the book bought out of cash on its first day."""
    build = [r for r in rows if r["session"] == 0]
    return build, [r for r in rows if r["session"] != 0]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ledgers = OUT / "ledgers"
    ledgers.mkdir(exist_ok=True)
    market = build_market("data/etf_bars.parquet", "data/corp_actions.parquet",
                          "evidence/sleeve_scores.parquet")
    clearing = clearing_table()
    code2sleeve = sleeve_map()

    cells: dict[str, dict] = {}
    for nav in NAVS:
        cell = Cell(nav, TOLERANCE, COST_MODE)
        result = e3.run_cell(market, cell, ledger_dir=ledgers, arms=("static", "lots"))
        entry = result["arms"]["lots"]
        path = ledgers / f"{cell.key}_lots.jsonl"
        rows = intents(path)
        build, maintenance = split(rows)
        stats = summarise(rows, clearing, code2sleeve)
        maint = summarise(maintenance, clearing, code2sleeve)
        builds = summarise(build, clearing, code2sleeve)
        # intents() returns fills *and* suppressions; the two are counted apart here because a
        # book can hold the same intent count while trading four times as much.
        maintenance_fills = [r for r in maintenance if r["kind"] == "fill"]
        head_here = LedgerStore(path).head
        recorded = Path("evidence/e3-ledgers") / f"{cell.key}_lots.jsonl"
        recorded_head = LedgerStore(recorded).head if recorded.exists() else None
        cells[cell.key] = {
            "nav0": float(nav),
            "intents": {k: stats[k] for k in ("n_intents", "n_zero_notional",
                                              "n_below_clearing", "below_share",
                                              "median_intent_cny", "below_share_ci95")},
            "maintenance": maint,
            "build": builds,
            "entry": entry["entry"],
            "entry_gap_pp": {s: round((float(entry["entry"][f"entry_{s}"]) - float(MANDATE[s])) * 100, 3)
                             for s in SLEEVES},
            "entry_codes": len(entry["entry"]["entry_codes"]),
            "n_fills": entry["n_fills"],
            "post_entry_intents": len(maintenance),
            "post_entry_fills": len(maintenance_fills),
            "post_entry_fill_notional_cny": round(sum(r["notional"] for r in maintenance_fills), 2),
            "ledger_head": head_here,
            "recorded_ledger_head": recorded_head,
            "reproduces_recorded_ledger": (recorded_head == head_here) if recorded_head else None,
            "turnover_per_year": entry["turnover_per_year"],
            "cost_bp_of_nav_per_year": entry["cost_bp_of_nav_per_year"],
            "intent_profile": {
                "clearing_min": entry["intent_profile"]["clearing_min_cny"],
                "clearing_median": entry["intent_profile"]["clearing_median_cny"],
                "clearing_max": entry["intent_profile"]["clearing_max_cny"],
            },
        }

    verdict = {"ref_50k": REF_50K, "cells": cells, "rule": "C1/C2/C3 pre-declared in the module docstring"}
    for key, cell in cells.items():
        share = cell["maintenance"]["below_share"]
        median = cell["maintenance"]["median_intent_cny"]
        bound = cell["intent_profile"]["clearing_median"]
        verdict[key] = {
            "C1_refuted": share >= 0.75,
            "C2_measured": share < 0.60 and median >= bound,
            "C3_composition_effect": share < REF_50K["maintenance_below_share"]
            and cell["post_entry_fills"] <= REF_50K["maintenance_fills"],
            "share": round(share, 4),
            "median_cny": median,
            "median_over_bound": round(median / bound, 3),
        }

    (OUT / "summary.json").write_text(json.dumps(verdict, indent=1, default=str), encoding="utf-8")

    lines = ["| cell | intents | below | share | median intent | median/bound | entry cash | "
             "post-entry intents | fills | codes |", "|---|---|---|---|---|---|---|---|---|---|"]
    for key, cell in cells.items():
        lines.append(
            f"| {key} | {cell['intents']['n_intents']} | {cell['intents']['n_below_clearing']} | "
            f"{cell['intents']['below_share']:.4f} | {cell['intents']['median_intent_cny']:.1f} | "
            f"{cell['intents']['median_intent_cny'] / cell['intent_profile']['clearing_median']:.3f} | "
            f"{cell['entry']['entry_cash']:.4f} | {cell['post_entry_intents']} | "
            f"{cell['post_entry_fills']} | {cell['entry_codes']} |")
    lines.append("")
    lines.append("maintenance regime only (session != 0):")
    lines.append("")
    for key, cell in cells.items():
        lines.append(f"- {key}: n={cell['maintenance']['n_intents']} "
                     f"fills={cell['post_entry_fills']} "
                     f"below={cell['maintenance']['n_below_clearing']} "
                     f"share={cell['maintenance']['below_share']:.4f} "
                     f"median={cell['maintenance']['median_intent_cny']:.1f} "
                     f"ratio={cell['maintenance']['median_intent_cny'] / cell['intent_profile']['clearing_median']:.3f} "
                     f"build: n={cell['build']['n_intents']} below_share={cell['build']['below_share']:.4f} "
                     f"median={cell['build']['median_intent_cny']:.1f}")
    lines.append("")
    lines.append(f"verdict: {json.dumps({k: v for k, v in verdict.items() if k not in ('ref_50k', 'cells', 'rule')})}")
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())