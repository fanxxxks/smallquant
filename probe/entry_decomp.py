"""Does the 2026 out-of-sample 'anomaly' come from the book being built, not traded?

Confirm-step artefact of ledger seq 114 (`probe-entry-decomp`). Reads only derived
artefacts: the chained replay ledgers of E3 (2016-2025) and of the 2026 confirm read,
plus venue.parquet for the code->sleeve map. No market-data read, so no window is claimed.

The question: probe-forward-2026 reported cost 9.3404 bp of NAV per year (against 1.6718
in sample) and per-sleeve fill ratios 0.958/1.000/0.833/0.926 (against 0.334/0.475/0.507/
0.561). The handoff reads those as two facts and supersedes the bp/yr criterion with
cost-per-turnover. Turnover is `traded / nav0 / years` (newquant/replay.py:925), so a book
that is BUILT once inside an 11-month window divides its whole build cost by 0.917 years,
while a book that already exists divides ten years of holding by ten. This probe splits
every fill into the initial build (session 0, from cash) and everything after it, and
recomputes both statistics per calendar year and entry-excluded.

Pre-declared rule (ledger seq 114):
  R1 if session-0 fills are >= 85% of 2026 traded notional AND >= 55% of 2026 total cost,
     the bp/yr spike is an un-amortised build, not a change in behaviour.
  R2 if the post-entry 2026 fill ratio falls inside the 2016-2025 per-year range, handoff
     unverified item 3 closes; else the post-2023 split explanation must be tested
     separately by comparing 2023-2025 against 2016-2022.
  R3 if session-0 fills are < 85% of 2026 notional, the 2026 segment is not stationary
     with the in-sample book.

Run: PYTHONPATH=. python probe/entry_decomp.py
"""

from __future__ import annotations

import bisect
import json
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

OUT = Path("evidence/probe-entry-decomp")
LEDGERS = {
    ("e3", "static"): "evidence/e3-ledgers/nav50000_tol15.1_measured_static.jsonl",
    ("e3", "lots"): "evidence/e3-ledgers/nav50000_tol15.1_measured_lots.jsonl",
    ("fwd", "static"): "evidence/probe-forward-2026/ledgers/nav50000_tol15.1_measured_static.jsonl",
    ("fwd", "lots"): "evidence/probe-forward-2026/ledgers/nav50000_tol15.1_measured_lots.jsonl",
}
NAV0 = 50_000.0


def sleeve_map() -> dict[str, str]:
    venue = pd.read_parquet("data/venue.parquet")[["code", "sleeve"]]
    return {str(c): str(s) for c, s in zip(venue["code"], venue["sleeve"])}


def session_years(rows: list[dict]) -> tuple[list[int], list[int]]:
    """Mark sessions are the only dated records: map each session forward to the year of
    the first mark at or after it (a fill in early January therefore lands in the new year,
    not on December's mark)."""
    marks = [(int(r["payload"]["session"]), str(r["payload"]["note"])) for r in rows
             if r["kind"] == "mark"]
    marks.sort()
    ms = [m[0] for m in marks]
    my = [int(m[1].rsplit("-", 1)[-1]) if False else int(m[1].split("month-end ")[1][:4])
          for m in marks]
    return ms, my


def year_of(session: int, ms: list[int], my: list[int]) -> int:
    i = bisect.bisect_left(ms, session)
    return my[i] if i < len(my) else my[-1]


def decompose(path: str, code2sleeve: dict[str, str]) -> dict:
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    ms, my = session_years(rows)
    years = sorted({year_of(int(r["payload"]["session"]), ms, my)
                    for r in rows if r["kind"] in ("fill", "suppress")})

    per_year: dict[int, dict] = {}
    for year in years:
        per_year[year] = {
            "fills": 0, "entry_fills": 0, "suppressions": 0,
            "traded_cny": 0.0, "entry_traded_cny": 0.0,
            "cost_cny": 0.0, "entry_cost_cny": 0.0,
            "sleeve_lots": defaultdict(lambda: {"filled": 0, "intended": 0}),
            "sleeve_lots_post": defaultdict(lambda: {"filled": 0, "intended": 0}),
            "reasons": Counter(),
        }

    for r in rows:
        kind = r["kind"]
        if kind not in ("fill", "suppress"):
            continue
        p = r["payload"]
        year = year_of(int(p["session"]), ms, my)
        cell = per_year[year]
        sleeve = code2sleeve.get(str(p.get("code")))
        entry = int(p.get("session", -1)) == 0
        if kind == "fill":
            lots = int(p["lots"])
            notional = abs(float(p["notional"]))
            cost = float(p["total_cost"])
            cell["fills"] += 1
            cell["traded_cny"] += notional
            cell["cost_cny"] += cost
            if entry:
                cell["entry_fills"] += 1
                cell["entry_traded_cny"] += notional
                cell["entry_cost_cny"] += cost
            if sleeve:
                cell["sleeve_lots"][sleeve]["filled"] += lots
                cell["sleeve_lots"][sleeve]["intended"] += lots
                if not entry:
                    cell["sleeve_lots_post"][sleeve]["filled"] += lots
                    cell["sleeve_lots_post"][sleeve]["intended"] += lots
        else:
            lots = int(p.get("intended_lots", 0))
            cell["suppressions"] += 1
            cell["reasons"][str(p.get("reason"))] += 1
            if sleeve:
                cell["sleeve_lots"][sleeve]["intended"] += lots
                if not entry:
                    cell["sleeve_lots_post"][sleeve]["intended"] += lots

    def ratios(bucket: dict) -> dict[str, float | None]:
        return {s: (b["filled"] / b["intended"] if b["intended"] else None)
                for s, b in bucket.items()}

    out = {}
    for year, cell in per_year.items():
        out[str(year)] = {
            "fills": cell["fills"],
            "entry_fills": cell["entry_fills"],
            "suppressions": cell["suppressions"],
            "traded_cny": round(cell["traded_cny"], 2),
            "entry_share_of_traded": (cell["entry_traded_cny"] / cell["traded_cny"]
                                      if cell["traded_cny"] else None),
            "cost_cny": round(cell["cost_cny"], 2),
            "entry_share_of_cost": (cell["entry_cost_cny"] / cell["cost_cny"]
                                    if cell["cost_cny"] else None),
            "cost_bp_of_nav": round(cell["cost_cny"] / NAV0 * 1e4, 2),
            "cost_bp_of_nav_post_entry": round(
                (cell["cost_cny"] - cell["entry_cost_cny"]) / NAV0 * 1e4, 2),
            "turnover": round(cell["traded_cny"] / NAV0, 4),
            "turnover_post_entry": round(
                (cell["traded_cny"] - cell["entry_traded_cny"]) / NAV0, 4),
            "fill_ratio_all": ratios(cell["sleeve_lots"]),
            "fill_ratio_post_entry": ratios(cell["sleeve_lots_post"]),
            "suppression_reasons": dict(cell["reasons"]),
        }
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    code2sleeve = sleeve_map()
    report = {f"{window}:{arm}": decompose(path, code2sleeve)
              for (window, arm), path in LEDGERS.items()}
    (OUT / "summary.json").write_text(json.dumps(report, indent=1), encoding="utf-8")

    lines: list[str] = []

    def emit(text: str = "") -> None:
        lines.append(text)
        print(text)

    for key, per_year in report.items():
        window, arm = key.split(":")
        emit(f"### {window} / {arm}")
        emit("| year | fills (entry) | suppr | traded CNY | entry% | cost CNY | cost bp/NAV | bp post-entry "
             "| turnover | turnover post | reasons |")
        emit("|---|---|---|---|---|---|---|---|---|---|---|")
        for year, c in per_year.items():
            emit(f"| {year} | {c['fills']} ({c['entry_fills']}) | {c['suppressions']} "
                 f"| {c['traded_cny']:,.0f} "
                 f"| {100 * (c['entry_share_of_traded'] or 0):.1f}% | {c['cost_cny']:,.2f} "
                 f"| {c['cost_bp_of_nav']:.2f} | {c['cost_bp_of_nav_post_entry']:.2f} "
                 f"| {c['turnover']:.3f} | {c['turnover_post_entry']:.3f} "
                 f"| {c['suppression_reasons']} |")
        emit("")

    # R1 / R3: entry dominance in the 2026 window
    fwd_lots = report["fwd:lots"]["2026"]
    r1 = ((fwd_lots["entry_share_of_traded"] or 0) >= 0.85
          and (fwd_lots["entry_share_of_cost"] or 0) >= 0.55)
    emit(f"R1 entry dominance 2026 lots: traded {100 * (fwd_lots['entry_share_of_traded'] or 0):.1f}% "
         f"(bar 85%), cost {100 * (fwd_lots['entry_share_of_cost'] or 0):.1f}% (bar 55%) -> "
         f"{'PASS' if r1 else 'FAIL'}")
    emit(f"R3 falsifier: {'not triggered' if r1 else 'TRIGGERED - 2026 not stationary'}")

    # R2: does the post-entry 2026 ratio fall inside the in-sample per-year range?
    in_sample = {y: c for y, c in report["e3:lots"].items() if y != "2026"}
    for sleeve in ("equity", "bond", "commodity", "overseas"):
        sample = [c["fill_ratio_all"].get(sleeve) for c in in_sample.values()]
        sample = [v for v in sample if v is not None]
        post = fwd_lots["fill_ratio_post_entry"].get(sleeve)
        inside = (post is not None and sample and min(sample) - 1e-12 <= post <= max(sample) + 1e-12)
        emit(f"R2 {sleeve}: 2016-2025 per-year range [{min(sample):.3f}, {max(sample):.3f}], "
             f"2026 post-entry {post if post is None else round(post, 3)} -> "
             f"{'INSIDE' if inside else 'OUTSIDE'}")
    emit("")

    # Cross-check: the in-sample entry year should look like the 2026 window.
    emit("Entry-year symmetry (2016 versus 2026, lots arm):")
    for year in ("2016", "2026"):
        c = report[f"{'e3' if year == '2016' else 'fwd'}:lots"][year]
        emit(f"  {year}: entry fills {c['entry_fills']}/{c['fills']}, "
             f"cost {c['cost_cny']:.2f} CNY = {c['cost_bp_of_nav']:.2f} bp of NAV, "
             f"turnover {c['turnover']:.3f}, ratios { {k: (None if v is None else round(v, 3)) for k, v in c['fill_ratio_all'].items()} }")
    emit("")

    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT/'summary.json'} and {OUT/'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())