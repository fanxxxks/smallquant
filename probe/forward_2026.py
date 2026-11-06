"""Out-of-sample conformance read on the unread 2026 segment.

Confirm step `forward-2026-conformance` (ledger seq 110). Every earlier read stopped at
2025-12-31; data/etf_bars.parquet runs to 2026-11-04, so this is the first read of
2026-01-02..2026-11-04 and the decision rule was fixed before it was taken.

Only `static` and `lots` are replayed: the `vol` and `rule` arms need
evidence/sleeve_scores.parquet, which ends 2025-12-31. The CNY difference over one year is
reported, not scored - a single year cannot decide it.

Run: PYTHONPATH=. python probe/forward_2026.py
"""

from __future__ import annotations

import json
import sys
import time
from decimal import Decimal
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conformance_dryrun import evaluate  # noqa: E402

from newquant.eval.e2 import Cell  # noqa: E402
from newquant.eval.e3 import BARS, CORP, SCORES, run_cell  # noqa: E402
from newquant.replay import build_market  # noqa: E402

OUT = Path("evidence/probe-forward-2026")
START = "2026-01-02"
END = "2026-11-04"
NAV0 = Decimal(50000)
TOLERANCE = Decimal("15.1")
COST_MODE = "measured"
# The 2016-2025 reference ratios were retired as a criterion at seq 126: they are maintenance-year
# mixtures being compared against a build-year ratio. The verdict's fill-ratio numbers stay in the
# artefact as a diagnostic only.


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ledgers = OUT / "ledgers"
    ledgers.mkdir(exist_ok=True)
    cell = Cell(nav0=NAV0, tolerance_bp=TOLERANCE, cost_mode=COST_MODE)
    market = build_market(BARS, CORP, SCORES, start=START, end=END)
    started = time.time()
    result = run_cell(market, cell, ledger_dir=ledgers, start=START, end=END,
                      arms=("static", "lots"), reference="static")
    elapsed = time.time() - started

    monthly = pd.concat(
        [frame.assign(arm=name) for name, frame in result["monthly"].items()],
        ignore_index=True,
    )
    monthly.to_parquet(OUT / "monthly.parquet")
    summary = {"cells": {"primary": {"arms": result["arms"]}}, "cell": result["cell"],
               "deltas": result["deltas"], "run": {"start": START, "end": END,
                                                   "elapsed_s": round(elapsed, 1)}}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")

    paths = {name: ledgers / f"{cell.key}_{name}.jsonl" for name in ("static", "lots")}
    verdict = evaluate(summary, monthly, paths, cell="primary", arm="lots", control_arm="static",
                       months_required=8)
    verdict["window"] = {"start": START, "end": END, "months": int(monthly["date"].nunique()),
                         "sessions": int(result["arms"]["lots"].get("daily_sessions", 0))}
    verdict["unscored"] = {"lots-static_cny_per_year": result["deltas"].get("lots-static"),
                           "note": "reported only: one year cannot decide a return claim"}
    (OUT / "verdict.json").write_text(json.dumps(verdict, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: verdict[k] for k in ("checks", "failed", "window")},
                     indent=1, default=str))
    print("ratios", {s: round(v["fill_ratio"], 4) if v["fill_ratio"] else None
                     for s, v in verdict["intent_fill"].items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
