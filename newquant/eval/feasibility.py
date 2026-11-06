"""Build step 4: the feasibility report. Model-free on purpose.

The question this answers is not "is there alpha". It is: **at 50-100 k CNY, with a 100-unit
board lot and a 5 CNY commission floor, which monthly trades are physically executable at
all?** Every number here is a property of price, lot size, and the fee schedule — no signal,
no fit, nothing that could be reverse-engineered into a backtest.

Three outputs:

A. THRESHOLD — smallest trade that clears tolerance T, as a fraction of NAV.
B. LADDER — for one instrument at one NAV, the smallest *whole-lot* order that clears T.
C. EXECUTABLE — using real monthly closes, how often a declared per-sleeve trade size
   actually clears T after lot flooring. Reported per instrument and per month, so the
   "unmeasurable at this capital" verdict (architecture doc F-113a8e8d-6) has a number.

The declared trade sizes are a *scenario grid*, not a claim about the future signal: the
report says "if monthly per-sleeve moves are f of NAV, this share of them is tradeable".
"""

from __future__ import annotations

import json
import math
from decimal import Decimal
from pathlib import Path

import pandas as pd

from ..venue import ETF_STD, gate_ok, min_notional, round_to_lots

NAVS = (50_000, 75_000, 100_000)
TOLERANCES = ("7.6", "10", "15.1", "30", "50", "75")
TRADE_FRACS = ("0.025", "0.05", "0.10", "0.125", "0.20")
TURNOVER_CAP = Decimal("6")  # annual, from the project conditions


def threshold_table() -> pd.DataFrame:
    rows = []
    for tol in TOLERANCES:
        bound = min_notional(Decimal(tol), "buy")
        for nav in NAVS:
            rows.append(
                {
                    "tolerance_bp": tol,
                    "min_order_cny": None if bound is None else str(bound),
                    "nav": nav,
                    "min_fraction_of_nav": None if bound is None else round(float(bound) / nav, 5),
                    "within_monthly_sleeve_budget":
                        None if bound is None
                        else bool(float(bound) / nav <= float(TURNOVER_CAP / 12 / 4)),
                }
            )
    return pd.DataFrame(rows)


def lot_ladder(price: Decimal, nav: int, tol: Decimal, max_lots: int = 40) -> dict:
    """Smallest whole-lot order that clears `tol`, plus the lots that fail on the way."""
    per_lot = price * 100
    failing = []
    for lots in range(1, max_lots + 1):
        notional = per_lot * lots
        ok, bp = gate_ok(notional, "buy", tol)
        if ok:
            return {"min_lots": lots, "notional": str(notional.quantize(Decimal("0.01"))),
                    "bp": str(bp.quantize(Decimal("0.01"))), "failing_lots": failing,
                    "fraction_of_nav": round(float(notional) / nav, 5)}
        failing.append({"lots": lots, "bp": str(bp.quantize(Decimal("0.01")))})
    return {"min_lots": None, "notional": None, "bp": None, "failing_lots": failing,
            "fraction_of_nav": None}


def executable_cells(bars: pd.DataFrame, venue: pd.DataFrame, tol: Decimal,
                     frac: Decimal) -> pd.DataFrame:
    """One row per (month, instrument): a declared trade of frac*NAV, floored, gated."""
    tradable = venue.loc[venue["tradable"], "code"].tolist()
    prices = bars[bars["code"].isin(tradable)].copy()
    prices["month"] = prices["date"].str.slice(0, 7)
    month_end = (prices.sort_values("date").groupby(["code", "month"]).tail(1)
                 [["code", "month", "date", "close"]])
    out = []
    for nav in NAVS:
        target = Decimal(frac) * nav
        for _, row in month_end.iterrows():
            price = Decimal(str(row["close"]))
            lots = round_to_lots(target, price, 100)
            notional = Decimal(lots) * price * 100 if lots else Decimal(0)
            ok, bp = gate_ok(notional, "buy", tol) if lots else (False, Decimal(0))
            out.append({"nav": nav, "tol": str(tol), "frac": str(frac), "code": row["code"],
                        "month": row["month"], "lots": lots, "notional": float(notional),
                        "bp": float(bp) if lots else None, "executable": bool(ok)})
    return pd.DataFrame(out)


def one_lot_drag(venue: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in venue.iterrows():
        for nav in NAVS:
            rows.append({"code": r["code"], "sleeve": r["sleeve"], "nav": nav,
                         "one_lot": r["lot_notional"],
                         "one_lot_pct_of_nav": round(r["lot_notional"] / nav, 4),
                         "tradable": bool(r["tradable"])})
    return pd.DataFrame(rows)


def action_granularity(venue: pd.DataFrame) -> pd.DataFrame:
    """The action set, expressed as a size rather than as a scenario grid.

    Two questions the cleared-cell table cannot answer, because it fixes a policy first:

    1. What is the *smallest executable action* on this instrument at this NAV, in % of NAV?
       The cost gate makes it `N_min(T) / NAV` after lot rounding. That is the resolution of
       the control, and it does not depend on any target weight.
    2. How many such lumps does the annual turnover budget allow? `turnover_cap * NAV / N_min`.
       This is what makes the annual cap a *pool* rather than a monthly allowance: if the pool
       buys many lumps, capital does not force uniform monthly sizing, and the binding object is
       the lump size, not the budget.
    """
    rows = []
    for tol in ("7.6", "10", "15.1", "30"):
        bound = min_notional(Decimal(tol), "buy")
        for nav in NAVS:
            for _, inst in venue.loc[venue["tradable"]].iterrows():
                price = Decimal(str(inst["close_last"]))
                if bound is None:
                    rows.append({"tol": tol, "nav": nav, "code": inst["code"],
                                 "sleeve": inst["sleeve"], "min_action": None,
                                 "min_action_pct": None, "annual_lumps": None})
                    continue
                lots = max(1, math.ceil(float(bound) / float(price * 100)))
                notional = price * 100 * lots
                while not gate_ok(notional, "buy", Decimal(tol))[0]:
                    lots += 1
                    notional = price * 100 * lots
                rows.append({
                    "tol": tol, "nav": nav, "code": inst["code"], "sleeve": inst["sleeve"],
                    "min_action": float(notional),
                    "min_action_pct": round(float(notional) / nav, 4),
                    "annual_lumps": int(TURNOVER_CAP * nav / notional),
                })
    return pd.DataFrame(rows)


def main(bars_path: Path, data_dir: Path, evidence_dir: Path) -> dict:
    from ..data.freeze import load

    venue, manifest = load(data_dir)
    bars = pd.read_parquet(bars_path).sort_values(["code", "date"]).reset_index(drop=True)

    thresholds = threshold_table()
    ladder = {}
    for code in venue.loc[venue["tradable"], "code"]:
        row = venue.set_index("code").loc[code]
        price = Decimal(str(row["close_last"]))
        ladder[code] = {"sleeve": row["sleeve"], "price": str(price),
                        "per_nav": {str(nav): {t: lot_ladder(price, nav, Decimal(t))
                                               for t in ("10", "15.1", "30")} for nav in NAVS}}

    drag = one_lot_drag(venue)
    granularity = action_granularity(venue)

    cells = []
    for tol in ("10", "15.1", "30"):
        for frac in TRADE_FRACS:
            cells.append(executable_cells(bars, venue, Decimal(tol), Decimal(frac)))
    grid = pd.concat(cells, ignore_index=True)
    grid = grid[grid["month"] >= "2016-01"]

    summary = (grid.groupby(["nav", "tol", "frac"])
               .agg(cells=("executable", "size"), cleared=("executable", "sum"))
               .reset_index())
    summary["cleared_share"] = (summary["cleared"] / summary["cells"]).round(4)

    per_instrument = (grid.groupby(["nav", "tol", "frac", "code"])
                      .agg(months=("executable", "size"), cleared=("executable", "sum"))
                      .reset_index())
    per_instrument["cleared_share"] = (per_instrument["cleared"] /
                                       per_instrument["months"]).round(4)

    report = {
        "venue_hash": manifest["venue_hash"],
        "bars_last_date": str(bars["date"].max()),
        "months": sorted(grid["month"].unique().tolist())[:1] +
                  sorted(grid["month"].unique().tolist())[-1:],
        "n_months": int(grid["month"].nunique()),
        "fee_profile": {k: str(v) for k, v in ETF_STD.__dict__.items()},
        "searches": {"tolerances_bp": list(TOLERANCES), "navs": list(NAVS),
                     "trade_fracs": list(TRADE_FRACS)},
    }

    evidence_dir.mkdir(parents=True, exist_ok=True)
    stem = f"feasibility-{manifest['venue_hash'][:8]}"
    grid.to_parquet(evidence_dir / f"{stem}.parquet", index=False)
    (evidence_dir / f"{stem}.json").write_text(
        json.dumps({"report": report, "thresholds": thresholds.to_dict("records"),
                    "ladder": ladder, "summary": summary.to_dict("records"),
                    "per_instrument": per_instrument.to_dict("records"),
                    "granularity": granularity.to_dict("records")},
                   ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    md = render(thresholds, summary, per_instrument, drag, report, granularity)
    (evidence_dir / f"{stem}.md").write_text(md, encoding="utf-8")
    return {"stem": stem, "report": report, "summary": summary, "thresholds": thresholds}


def render(thresholds, summary, per_instrument, drag, report, granularity=None) -> str:
    lines = [
        f"# Feasibility at {', '.join(f'{n:,}' for n in NAVS)} CNY",
        "",
        f"venue hash `{report['venue_hash']}` · bars to {report['bars_last_date']} · "
        f"{report['n_months']} months · fee profile `{report['fee_profile']['name']}`",
        "",
        "Model-free: price × lot size × fee schedule only. A monthly trade of `f × NAV` is",
        "floored to whole lots and then put through the same gate the account uses.",
        "",
        "## A. Smallest trade that clears a tolerance",
        "",
        "| tol (bp) | min order (CNY) | 50 k | 75 k | 100 k | inside the 12.5 %/sleeve budget |",
        "|---|---|---|---|---|---|",
    ]
    for tol in TOLERANCES:
        sub = thresholds[thresholds["tolerance_bp"] == tol]
        first = sub.iloc[0]
        cells = " | ".join(
            "—" if r["min_fraction_of_nav"] is None else f"{r['min_fraction_of_nav']:.2%}"
            for _, r in sub.iterrows())
        budget = "—" if first["within_monthly_sleeve_budget"] is None else \
            ("yes" if first["within_monthly_sleeve_budget"] else "**no**")
        lines.append(f"| {tol} | {first['min_order_cny'] or 'never'} | {cells} | {budget} |")

    lines += [
        "",
        f"Annual turnover ≤ {TURNOVER_CAP} → monthly total ≤ {float(TURNOVER_CAP) / 12:.1%} of NAV",
        f"→ {float(TURNOVER_CAP) / 12 / 4:.2%} per sleeve across four investable sleeves.",
        "",
        "## B. Cleared share of (month × instrument) cells",
        "",
    ]
    pivot = summary.pivot_table(index=["tol", "frac"], columns="nav", values="cleared_share")
    lines.append("| tol (bp) | trade/sleeve | 50 k | 75 k | 100 k |")
    lines.append("|---|---|---|---|---|")
    for (tol, frac), row in pivot.iterrows():
        cells = " | ".join("n/a" if pd.isna(row.get(nav)) else f"{row[nav]:.1%}" for nav in NAVS)
        lines.append(f"| {tol} | {float(frac):.1%} | {cells} |")

    lines += ["", "## C. One-lot drag (smallest possible position)", "",
              "| code | sleeve | one lot (CNY) | 50 k | 75 k | 100 k |", "|---|---|---|---|---|---|"]
    for code, g in drag.groupby("code"):
        r0 = g.iloc[0]
        cells = " | ".join(f"{r['one_lot_pct_of_nav']:.2%}" for _, r in g.iterrows())
        flag = "" if r0["tradable"] else " ⚠"
        lines.append(f"| {code}{flag} | {r0['sleeve']} | {r0['one_lot']:,.0f} | {cells} |")

    if granularity is not None and not granularity.empty:
        lines += ["", "## E. Action granularity (smallest executable move, and the annual pool)", "",
                  "| tol (bp) | NAV | min action (CNY) | % NAV | lumps the annual cap allows |",
                  "|---|---|---|---|---|"]
        agg = (granularity.dropna(subset=["min_action_pct"])
               .groupby(["tol", "nav"])
               .agg(min_action=("min_action", "min"), pct=("min_action_pct", "min"),
                    lumps=("annual_lumps", "min"))
               .reset_index())
        for _, r in agg.iterrows():
            lines.append(f"| {r['tol']} | {r['nav']:,} | {r['min_action']:,.0f} | "
                         f"{r['pct']:.1%} | {r['lumps']} |")
        lines += ["", "The second column is the resolution of the control, the last is how many",
                  "such moves the annual turnover cap funds. Where the first is large the signal",
                  "cannot be expressed as a small adjustment; where the last is small the budget,",
                  "not the gate, is binding."]

    worst = per_instrument.sort_values("cleared_share").head(5)
    lines += ["", "## D. Least executable instruments (30 bp, 10 %/sleeve)", ""]
    for _, r in worst.iterrows():
        if float(r["tol"]) != 30:
            continue
        lines.append(f"- `{r['code']}` NAV {r['nav']:,}: {r['cleared']}/{r['months']} months "
                     f"({r['cleared_share']:.1%})")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    import argparse

    root = Path(__file__).resolve().parents[2]
    p = argparse.ArgumentParser()
    p.add_argument("--bars", default=str(root / "data" / "etf_bars.parquet"))
    p.add_argument("--data", default=str(root / "data"))
    p.add_argument("--evidence", default=str(root / "evidence"))
    a = p.parse_args()
    out = main(Path(a.bars), Path(a.data), Path(a.evidence))
    print(out["stem"])
    print(out["summary"].to_string(index=False))
