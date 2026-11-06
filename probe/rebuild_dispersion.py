"""Rebuild the sleeve-dispersion summary from the ledgers on disk.

The replays completed; only the member-CAGR tail of probe/sleeve_dispersion.py crashed on an
arrow string index.  Terminal NAV lives in each ledger's last mark record, so the table is
rebuilt here instead of paying for another 90 replays.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from newquant.replay import SLEEVE_MEMBERS, build_market

LEDGERS = Path("/d/tmp/rd_disp")
OUT = Path("evidence/probe-sleeve-dispersion")
FIRST, END = "2016-01-04", "2026-11-04"
STARTS = ("2016-01-04", "2017-04-05", "2018-07-02",
          "2020-01-02", "2021-10-08", "2023-10-09")
SLEEVES = {k: tuple(v) for k, v in SLEEVE_MEMBERS.items()}


def last_nav(path: Path) -> float:
    nav = None
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            p = rec.get("payload") or {}
            if rec.get("kind") == "mark" and p.get("nav"):
                nav = float(p["nav"])
    return nav


def main() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    market = build_market("data/etf_bars.parquet", "data/corp_actions.parquet",
                          "evidence/sleeve_scores.parquet", start=FIRST, end=END)
    cells = {}
    for path in sorted(LEDGERS.glob("*.jsonl")):
        stem = path.stem
        if "__" not in stem:
            continue  # hold__<start> and any other non-cell ledger
        sleeve, rest = stem.split("__", 1)
        if "__" not in rest:
            continue
        tag, start = rest.rsplit("__", 1)
        nav = last_nav(path)
        if nav is None:
            continue
        cells.setdefault(sleeve, {}).setdefault(start, {})[tag] = nav
    print({s: {st: len(v) for st, v in d.items()} for s, d in cells.items()})

    disp = {}
    for sleeve, by_start in cells.items():
        disp[sleeve] = {}
        for start, navs in by_start.items():
            vals = list(navs.values())
            disp[sleeve][start] = (max(vals) - min(vals)) / (sum(vals) / len(vals)) * 100.0
    flat = {s: [v for st, v in sorted(d.items())] for s, d in disp.items()}
    agg = {s: sum(v) / len(v) for s, v in flat.items()}

    cagr = {}
    for sleeve, members in SLEEVES.items():
        rates = {}
        for code in members:
            try:
                s = market.close_of(code)
            except (KeyError, TypeError):
                continue
            if s is None or len(s) < 2:
                continue
            s = s[[str(i) >= "2017-04-05" for i in s.index]]
            if len(s) < 2:
                continue
            yrs = (pd.Timestamp(str(s.index[-1])) - pd.Timestamp(str(s.index[0]))).days / 365.25
            rates[code] = ((float(s.iloc[-1]) / float(s.iloc[0])) ** (1 / yrs) - 1) * 100
        cagr[sleeve] = {"members": rates,
                        "spread_pp": (max(rates.values()) - min(rates.values())) if len(rates) > 1 else 0.0}

    ok = all(disp["commodity"][s] <= 0.25 * disp["overseas"][s] for s in disp["commodity"])
    if ok and cagr["commodity"]["spread_pp"] < 1.0:
        verdict = "exposure-reading-supported"
    else:
        verdict = "reading-incomplete: dispersion is not proportional to underlying difference"

    summary = {"probe": "sleeve-dispersion(rebuilt)", "nav0": 50000.0, "starts": list(STARTS),
               "dispersion_pct": disp, "dispersion_mean_pct": agg,
               "member_cagr": cagr, "terminal_nav": cells, "verdict": verdict,
               "source": "ledgers at D:/d/tmp/rd_disp; note a python Path of /d/tmp/x lands on D:/d/tmp/x here, not D:/tmp/x"}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    lines = ["# How much does the member-ordering lottery cost, by sleeve?", "",
             "50 000 CNY, base regime (15.1 bp gate, lot floor), every distinct ordering of each "
             "sleeve's listed members, 2016-01-04..2026-11-04.  Dispersion = (max-min)/mean of "
             "terminal NAV across orderings, per cent.", "",
             "| sleeve | mean dispersion (%) | member CAGR spread (pp/yr) | member CAGRs |",
             "|---|---|---|---|"]
    for sleeve in agg:
        r = cagr[sleeve]
        lines.append(f"| {sleeve} | {agg[sleeve]:.3f} | {r['spread_pp']:.2f} | " +
                     ", ".join(f"{c} {v:.2f}" for c, v in sorted(r["members"].items())) + " |")
    lines += ["", "| sleeve | " + " | ".join(STARTS) + " |", "|---|" + "---|" * len(STARTS)]
    for sleeve in agg:
        lines.append(f"| {sleeve} | " + " | ".join(f"{disp[sleeve][s]:.2f}" for s in STARTS) + " |")
    lines += ["", f"**Verdict:** {verdict}", ""]
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"verdict": verdict,
                      "dispersion": {k: round(v, 3) for k, v in agg.items()},
                      "cagr_spread": {k: round(v["spread_pp"], 2) for k, v in cagr.items()}},
                     indent=2))
    return summary


if __name__ == "__main__":
    main()
