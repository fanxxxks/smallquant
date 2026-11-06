"""Does a *simpler* policy dominate the adopted book at every entry start?

The success criterion's first branch has never been run at decision grade.  The one paired grid
that exists (32 quarterly starts, evidence/probe-hold-kill/quarterly-paired.json) compared
``lots`` against ``hold_lot`` — the SAME lot-defined construction with its annual re-submission
removed.  That isolates maintenance; it says nothing about whether the construction itself earns
anything, because both arms carry the lot machinery.

The prespecified simpler policy is the declared mandate bought once and held, paying its real
one-off entry cost: ``hold`` at a tolerance its build orders actually clear.  At 15.1 bp it cannot
express two of four sleeves (overseas and commodity always 0 %, cash 37-41 %), so the honest form
is ``hold@200``: measured 0 suppressions, entry cost 0.90 bp/yr of NAV, i.e. ~20 CNY once.  The
single 2016 cell already had it ahead of ``lots@15.1`` on terminal, daily vol, daily maxDD AND
cost at the same time (evidence/probe-hold-kill/gate-decomp.json); one start cannot decide it.

PRE-DECLARED (ledger seq 179, run-39aad9d7, before any number from this script):
  R0 reproduction - ``lots@15.1`` at all 32 recorded starts must match the recorded nav to
     +-0.01, and ``hold_lot@15.1`` likewise; else the build convention differs and no arm quotes.
  R1 return, ONE-SIDED - simpler arm H is not worse at a start when nav_H >= nav_lots*(1-0.02).
     A two-sided band would score a simpler policy that beats the adopted book by >2 % as a
     failure and invert the criterion's purpose.
  R2 risk - maxDD_H >= mdd_lots - 1.0 pp AND vol_H <= vol_lots + 1.0 pp (daily-marked).
  R3 a start passes when R1 and R2 hold.
  Branch A (construction retires): >= 30/32 pass and paired mean annualised gap >= 0.
  Branch B (construction has a measured reason): < 20/32 pass, or H is worse than the band at
     >= 8 starts.
  Branch C: 20-29 pass -> unresolved; attribution only, decide nothing.
  Secondary attribution: {lots,hold} x {15.1,200}.  If hold@15.1/hold@200 sits near the single
     cell's 0.666 at most starts, the gate — not the lot rule — is what the adopted book paid for.

This is a screen on windows already observed by run-5a92eb45; a final claim needs an unread set.
"""

from __future__ import annotations

import argparse
import json
import math
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from newquant.replay import ARMS, build_market, replay
from probe.hold_kill import daily_metrics

NAV0 = Decimal("50000")
COST_MODE = "measured"
END = "2026-11-04"
FIRST = "2016-01-04"

RETURN_TOL = 0.02     # one-sided, inherited magnitude from seq 152
RISK_TOL_PP = 1.0     # inherited from seq 152

RECORDED = Path("evidence/probe-hold-kill/quarterly-paired.json")
OUT = Path("evidence/probe-retirement")
LEDGERS = Path("/tmp/rd_ledgers")

# (tag, arm, tolerance_bp)
CONFIGS = (
    ("lots@15.1", "lots", Decimal("15.1")),
    ("lots@200", "lots", Decimal("200")),
    ("hold@15.1", "hold", Decimal("15.1")),
    ("hold@200", "hold", Decimal("200")),
    ("hold_lot@15.1", "hold_lot", Decimal("15.1")),
    ("hold_lot@200", "hold_lot", Decimal("200")),
)
CHECK_CONFIGS = ("lots@15.1", "hold_lot@15.1")


def cell(res, nav0: Decimal) -> dict:
    last = res.monthly.iloc[-1]
    first = res.monthly.iloc[0]
    return {
        "nav_end": float(res.stats["nav_end"]),
        "cagr_calendar": None,          # filled by daily_metrics
        "max_drawdown_daily": None,
        "vol_annual_252": None,
        "n_fills": int(res.stats["n_fills"]),
        "n_suppressed": int(len(res.suppressions)),
        "cost_bp_of_nav_per_year": float(res.stats["cost_bp_of_nav_per_year"]),
        "entry_cash_share": float(first["cash"] / first["nav"]),
        "cash_end_share": float(last["cash"] / last["nav"]),
        "realised_equity_end": float(last["realised_equity"]),
        "realised_bond_end": float(last["realised_bond"]),
        "realised_commodity_end": float(last["realised_commodity"]),
        "realised_overseas_end": float(last["realised_overseas"]),
        **daily_metrics(res.daily, nav0),
    }


def main(check_only: bool = False) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    LEDGERS.mkdir(parents=True, exist_ok=True)
    recorded = json.loads(RECORDED.read_text(encoding="utf-8"))
    starts = [r["start"] for r in recorded]
    ref = {r["start"]: r for r in recorded}

    market = build_market("data/etf_bars.parquet", "data/corp_actions.parquet",
                          "evidence/sleeve_scores.parquet", start=FIRST, end=END)

    configs = [c for c in CONFIGS if (not check_only or c[0] in CHECK_CONFIGS)]
    rows: dict[str, dict[str, dict]] = {c[0]: {} for c in configs}
    for i, start in enumerate(starts, 1):
        for tag, arm, tol in configs:
            path = LEDGERS / f"{tag.replace('.', '_')}__{start}.jsonl"
            res = replay(market, ARMS[arm], nav0=NAV0, tolerance_bp=tol, cost_mode=COST_MODE,
                         ledger_path=path, start=start, end=END)
            rows[tag][start] = cell(res, NAV0)
        print(f"[{i}/{len(starts)}] {start} "
              + "  ".join(f"{t}={rows[t][start]['nav_end']:,.0f}" for t, _, _ in configs),
              flush=True)

    # ---- R0: does the build convention reproduce the recorded grid? ----------
    rep = {}
    for tag in CHECK_CONFIGS:
        if tag not in rows:
            continue
        key = "lots" if tag.startswith("lots") else "hold_lot"
        diffs = [abs(rows[tag][s]["nav_end"] - ref[s][key]) for s in starts]
        rep[tag] = {"max_abs_diff_cny": max(diffs), "n_match_cent": int(sum(d <= 0.011 for d in diffs))}
    rep["ok"] = all(v["max_abs_diff_cny"] <= 0.011 for k, v in rep.items() if k != "ok")
    if check_only:
        out = {"probe": "retirement-dominance", "mode": "check", "reproduction": rep}
        (OUT / "check.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        return out

    # if the conventions disagree, the honest fallback is a per-start market build; report it,
    # never silently quote arms computed on a grid that does not reproduce
    if not rep["ok"]:
        out = {"probe": "retirement-dominance", "reproduction": rep,
               "verdict": "invalid_experiment: build convention does not reproduce the recorded grid"}
        (OUT / "summary.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        return out

    # ---- R1-R3 per start, simpler policy = hold@200 -------------------------
    base, alt = "lots@15.1", "hold@200"
    per_start = []
    for s in starts:
        b, h = rows[base][s], rows[alt][s]
        years = b["years_calendar"]
        gap_pp = ((h["nav_end"] / b["nav_end"]) ** (1.0 / years) - 1.0) * 100.0
        r1 = h["nav_end"] >= b["nav_end"] * (1.0 - RETURN_TOL)
        r2 = (h["max_drawdown_daily"] >= b["max_drawdown_daily"] - RISK_TOL_PP / 100.0
              and h["vol_annual_252"] <= b["vol_annual_252"] + RISK_TOL_PP / 100.0)
        per_start.append({
            "start": s, "years": years,
            "lots_nav": b["nav_end"], "hold200_nav": h["nav_end"],
            "ratio": h["nav_end"] / b["nav_end"], "gap_pp_yr": gap_pp,
            "lots_mdd": b["max_drawdown_daily"], "hold200_mdd": h["max_drawdown_daily"],
            "d_mdd_pp": (h["max_drawdown_daily"] - b["max_drawdown_daily"]) * 100.0,
            "lots_vol": b["vol_annual_252"], "hold200_vol": h["vol_annual_252"],
            "d_vol_pp": (h["vol_annual_252"] - b["vol_annual_252"]) * 100.0,
            "cost_bp_lots": b["cost_bp_of_nav_per_year"],
            "cost_bp_hold200": h["cost_bp_of_nav_per_year"],
            "entry_cash_lots": b["entry_cash_share"], "entry_cash_hold200": h["entry_cash_share"],
            "pass_r1": bool(r1), "pass_r2": bool(r2), "pass": bool(r1 and r2),
        })
    n_pass = sum(p["pass"] for p in per_start)
    gaps = np.array([p["gap_pp_yr"] for p in per_start])
    mean_gap = float(gaps.mean())
    sd_gap = float(gaps.std(ddof=1))
    se_gap = sd_gap / math.sqrt(len(gaps))
    n_worse = sum(1 for p in per_start if not p["pass_r1"] and p["hold200_nav"] < p["lots_nav"])

    if n_pass >= 30 and mean_gap >= 0:
        branch, verdict = "A", "construction-retires"
    elif n_pass < 20 or n_worse >= 8:
        branch, verdict = "B", "construction-has-a-measured-reason"
    else:
        branch, verdict = "C", "unresolved-attribution-only"

    # ---- secondary: 2x2 attribution ----------------------------------------
    attr = {}
    for a, b2 in (("hold@15.1", "hold@200"), ("lots@15.1", "lots@200"),
                  ("hold@200", "hold_lot@200"), ("lots@15.1", "hold_lot@15.1")):
        ratios = [rows[a][s]["nav_end"] / rows[b2][s]["nav_end"] for s in starts]
        attr[f"{a}/{b2}"] = {"mean": float(np.mean(ratios)), "min": float(np.min(ratios)),
                             "max": float(np.max(ratios)),
                             "gt_1_count": int(sum(r > 1.0 for r in ratios))}

    summary = {
        "probe": "retirement-dominance",
        "declared": {"RETURN_TOL_one_sided": RETURN_TOL, "RISK_TOL_PP": RISK_TOL_PP,
                     "branch_A": ">=30/32 pass and mean gap >= 0",
                     "branch_B": "<20/32 pass or worse-than-band at >=8 starts"},
        "window": {"first_start": FIRST, "end": END, "n_starts": len(starts)},
        "cell": {"nav0": float(NAV0), "cost_mode": COST_MODE},
        "reproduction": rep,
        "primary": {"base": base, "alt": alt, "n_pass": n_pass, "n_starts": len(starts),
                    "mean_gap_pp_yr": mean_gap, "sd_gap_pp_yr": sd_gap, "se_gap_pp_yr": se_gap,
                    "t": mean_gap / se_gap if se_gap else None,
                    "ci95_pp_yr": [mean_gap - 1.96 * se_gap, mean_gap + 1.96 * se_gap],
                    "n_hold200_worse": n_worse,
                    "branch": branch, "verdict": verdict},
        "attribution": attr,
        "per_start": per_start,
        "arms": {tag: {s: {k: v for k, v in rows[tag][s].items()} for s in starts}
                 for tag in rows},
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                     encoding="utf-8")
    (OUT / "report.md").write_text(_report(summary), encoding="utf-8")
    return summary


def _report(s: dict) -> str:
    p, pr = s["primary"], s["per_start"]
    lines = [
        "# 成功判据第一支的决策级检验：更简单的政策在入场起点维度是否占优",
        "",
        f"{s['window']['n_starts']} 个季度起点，统一终点 {s['window']['end']}，"
        f"资本 {s['cell']['nav0']:.0f}，费率 {s['cell']['cost_mode']}，日频标记。",
        "",
        f"预注册（seq 179）：R1 单边 2%（更简单的政策更好不算失败）、R2 日频 maxDD/vol 各 1.0 pp；"
        f"判据 A ≥30/32 通过且配对均值 ≥0；判据 B <20/32 或 ≥8 个起点落后出带。",
        "",
        f"复现闸门：**{'通过' if s['reproduction']['ok'] else '失败'}** "
        f"{ {k: v for k, v in s['reproduction'].items() if k != 'ok'} }",
        "",
        f"对比 `{p['base']}` 对 `{p['alt']}`：通过 **{p['n_pass']}/{p['n_starts']}**，"
        f"配对年化 gap 均值 **{p['mean_gap_pp_yr']:+.3f} pp**（sd {p['sd_gap_pp_yr']:.3f}，"
        f"se {p['se_gap_pp_yr']:.3f}，t {p['t']:.2f}，95% CI "
        f"[{p['ci95_pp_yr'][0]:+.3f}, {p['ci95_pp_yr'][1]:+.3f}]），"
        f"更简单政策更差 {p['n_hold200_worse']} 个起点 → **分支 {p['branch']}: {p['verdict']}**",
        "",
        "## 逐起点",
        "",
        "| 起点 | 年数 | lots 终值 | hold@200 终值 | 比 | gap pp/yr | Δmdd pp | Δvol pp | 成本 bp/yr | 过 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for x in pr:
        lines.append(
            f"| {x['start']} | {x['years']:.2f} | {x['lots_nav']:,.0f} | {x['hold200_nav']:,.0f} | "
            f"{x['ratio']:.4f} | {x['gap_pp_yr']:+.2f} | {x['d_mdd_pp']:+.2f} | "
            f"{x['d_vol_pp']:+.2f} | {x['cost_bp_lots']:.2f} / {x['cost_bp_hold200']:.2f} | "
            f"{'Y' if x['pass'] else 'n'} |")
    lines += ["", "## 归因（比值 A/B，仅归因不判定）", "", "| 对比 | 均值 | 最小 | 最大 | A>B 的起点数 |",
              "|---|---|---|---|---|"]
    for k, v in s["attribution"].items():
        lines.append(f"| `{k}` | {v['mean']:.4f} | {v['min']:.4f} | {v['max']:.4f} | "
                     f"{v['gt_1_count']}/{len(pr)} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    out = main(check_only=a.check)
    print(json.dumps(out.get("reproduction") or out.get("primary"), indent=2, ensure_ascii=False))