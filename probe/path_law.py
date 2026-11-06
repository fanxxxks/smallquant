"""R1: does the member-count law hold on the PATH, or only at entry?

The direction review (round-6f4b2aac, R1) objected that the entry probe validated a closed form
against entry fills only, while on the path the engine composes from existing positions with
suppressed incremental orders and a NAV that already contains prior decisions.  This probe
replays the base regime and compares, at every month-end where the engine actually COMPOSED
(`members_overseas > 0`, i.e. `members_map` was populated - it reads 0 on a month-end that
returned no target), the engine's count against the closed form evaluated at that very NAV.

  k_law = max{k : (w_ovs * nav)/k >= sleeve_floor(available[:k])}

reported twice: with `w_ovs` = MANDATE["overseas"] (the entry-time law) and with `w_ovs` =
the row's own `aimed_overseas` (the path law).  The second is the honest path version, because
the lots arm derives the sleeve weight from the equity target via `sleeve_weights`, so 0.10 is
only correct in annual months.

PRE-DECLARED: agreement is a diagnostic, not a pass/fail.  If the aimed-weight form agrees on
every composition row, R1 is answered "the law generalises, the entry probe merely tested one
point of it".  If it disagrees, the mismatches are listed with aimed and realised sleeve weights
so the failure mode is on the record.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import newquant.replay as rp
from newquant.replay import ARMS, MANDATE, build_market, replay, slippage_table, TRADED

NAV0 = Decimal("50000")
TOL = Decimal("15.1")
COST_MODE = "measured"
FIRST, END = "2016-01-04", "2026-11-04"
STARTS = ("2016-01-04", "2017-04-05", "2018-07-02",
          "2020-01-02", "2021-10-08", "2023-10-09")
OUT = Path("evidence/probe-path-law")
LEDGERS = Path("/d/tmp/rd_path")


def law(market, nav: Decimal, weight: float, date: str, slippage) -> int:
    available = rp.available_members(market, "overseas", date)
    if not available:
        return 0
    budget = Decimal(str(weight)) * nav
    k = len(available)
    while k > 1 and budget / k < rp.sleeve_floor(market, available[:k], date, TOL, slippage):
        k -= 1
    return k


def main() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    LEDGERS.mkdir(parents=True, exist_ok=True)
    market = build_market("data/etf_bars.parquet", "data/corp_actions.parquet",
                          "evidence/sleeve_scores.parquet", start=FIRST, end=END)
    slippage = slippage_table(market, TRADED, mode=COST_MODE)

    rows, per_start = [], {}
    for start in STARTS:
        res = replay(market, ARMS["lots"], nav0=NAV0, tolerance_bp=TOL, cost_mode=COST_MODE,
                     ledger_path=LEDGERS / f"base__{start}.jsonl", start=start, end=END)
        n_dec, n_mandate, n_aimed = 0, 0, 0
        for _, r in res.monthly.iterrows():
            engine_k = int(r.get("members_overseas") or 0)
            if engine_k == 0:
                continue
            date = str(r["date"])[:10]
            nav = Decimal(str(r["nav"]))
            w_aim = float(r["aimed_overseas"])
            k_mandate = law(market, nav, float(MANDATE["overseas"]), date, slippage)
            k_aimed = law(market, nav, w_aim, date, slippage)
            n_dec += 1
            n_mandate += int(k_mandate == engine_k)
            n_aimed += int(k_aimed == engine_k)
            rows.append({"start": start, "date": date, "nav": float(nav),
                         "engine_k": engine_k, "aimed_overseas": w_aim,
                         "realised_overseas": float(r["realised_overseas"]),
                         "k_mandate": k_mandate, "k_aimed": k_aimed,
                         "available": list(rp.available_members(market, "overseas", date))})
        per_start[start] = {"decision_rows": n_dec, "agree_mandate": n_mandate,
                            "agree_aimed": n_aimed}
        print(f"{start}: {n_dec} composition rows, mandate-weight law {n_mandate}/{n_dec}, "
              f"aimed-weight law {n_aimed}/{n_dec}", flush=True)

    total = sum(v["decision_rows"] for v in per_start.values())
    tot_m = sum(v["agree_mandate"] for v in per_start.values())
    tot_a = sum(v["agree_aimed"] for v in per_start.values())
    summary = {"probe": "path-law", "nav0": float(NAV0), "starts": list(STARTS),
               "decision_rows": total,
               "agree_mandate_weight": tot_m, "agree_aimed_weight": tot_a,
               "per_start": per_start,
               "mismatches": [r for r in rows if r["k_aimed"] != r["engine_k"]],
               "rows": rows,
               "verdict": ("law-holds-on-path" if tot_a == total else "law-fails-on-path")}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = ["# Member-count law on the path", "",
             f"{total} composition month-ends across {len(STARTS)} starts, 50 000 CNY, "
             f"tolerance 15.1 bp.", "",
             "| start | composition rows | law vs MANDATE weight | law vs aimed weight |",
             "|---|---|---|---|"]
    for start, v in per_start.items():
        lines.append(f"| {start} | {v['decision_rows']} | {v['agree_mandate']} | "
                     f"{v['agree_aimed']} |")
    lines += ["", f"**{summary['verdict']}** — aimed-weight law agrees on {tot_a}/{total} rows, "
              f"MANDATE-weight law on {tot_m}/{total}.", ""]
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"verdict": summary["verdict"], "rows": total,
                      "agree_aimed": tot_a, "agree_mandate": tot_m}, indent=2))
    return summary


if __name__ == "__main__":
    main()