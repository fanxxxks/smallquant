"""Kill probe: can a buy-once policy reproduce the adopted lots book at one entry start?

The question this answers (docs/review-2026-11-05.md §4.1): on the realised 2016-01-04 ..
2025-12-31 path, at 50 000 CNY, the same 15.1 bp gate and the same ``etf_std`` fee schedule,
does a policy that buys the book once and never submits another target reproduce the adopted
arm's terminal net CNY and its daily-marked risk?  If it does, the lot rule and the annual
re-submission earn nothing on this path and the construction retires; if it does not, the
construction has, for the first time, a measured reason to exist here.

PRE-DECLARED BEFORE THE RUN (ledger ``hold-kill-single-cell``, seq 152).  Nothing below was
chosen after a number was seen:

  reproduction gate (fails => invalid_experiment, no arm may be quoted)
      static nav_end 62 163.64 +-0.01, 6 fills, chain head db6a4f19...
      lots   nav_end 85 111.30 +-0.01, chain head 02fb6458...
      lots - static annual_cny 1 542.7945 +-0.05
  RETURN_TOL = 2 % of the lots terminal net CNY   (|hold_end / lots_end - 1| <= 0.02)
  RISK_TOL   = 1.0 pp                             (daily maxDD no worse than lots by >1.0 pp
                                                   and daily annualised vol no higher by >1.0 pp)

READING RULE, one-sided:
  * a hold arm failing either clause at this start refutes retirement *for that arm at this
    start* — it does not prove the construction earns anything at the other eleven;
  * a hold arm passing both clauses at this start is NOT evidence for retirement either: the
    criterion is quantified over twelve entry starts, and one start cannot certify it.  A pass
    means the grid must run, nothing more.
So this probe can only kill the retirement direction.  It was written to do exactly that.

WHY THREE HOLD ARMS.  "Buy once" hides two different decisions, and the recorded evidence says
they are not the same lever (evidence/probe-ablation: the lots-vs-static gain is commodity +
overseas exposure, not the bond sleeve).  Splitting them costs one replay each:
  hold         MANDATE through the ordinary weight path        == static's entry book, frozen
  hold_lot     lot-defined composition, residual to cash       == lots' entry book, frozen
  hold_deploy  lot-defined composition, residual redeployed    == lots_deploy's book, frozen
hold_deploy is the honest competitor: it is a policy a person can write down and hold, and
lots - hold_deploy isolates the value of re-submitting every January and nothing else.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from newquant.eval.e2 import _cny_block, _delta_series, _head
from newquant.eval.e3 import _entry_realisation
from newquant.replay import REPLAY_END, REPLAY_START, ARMS, build_market, replay, slippage_table

# ---- pre-declared constants (a change here invalidates the ledger pre-registration) ----------
RETURN_TOL = 0.02
RISK_TOL_PP = 1.0

NAV0 = Decimal("50000")
TOLERANCE = Decimal("15.1")
COST_MODE = "measured"
START, END = REPLAY_START, REPLAY_END

BASELINE = "lots"
ARMS_RUN = ("static", "lots", "hold", "hold_lot", "hold_deploy")
HOLD_ARMS = ("hold", "hold_lot", "hold_deploy")

GATE_NAV_TOL = 0.01
GATE_DELTA_TOL = 0.05
E3_SUMMARY = Path("evidence/e3-summary.json")


def daily_metrics(daily: pd.DataFrame, nav0: Decimal) -> dict:
    """Daily-marked risk, the basis the criterion is written on.

    Convention, declared here because the earlier probe that first produced these numbers was
    disposable and its convention was never written down: returns are simple session returns off
    the per-session NAV, volatility is the sample sd times sqrt(252), drawdown runs on the wealth
    series [nav0] + NAV so the entry cost is inside it.  Two CAGR conventions are reported
    because the recorded 6.01 % cannot be re-derived from a 10-year terminal (see the reading).
    """
    nav = daily["nav"].to_numpy(dtype="float64")
    wealth = np.concatenate([[float(nav0)], nav])
    rets = wealth[1:] / wealth[:-1] - 1.0
    peak = np.maximum.accumulate(wealth)
    mdd = float((wealth / peak - 1.0).min())
    vol = float(np.std(rets, ddof=1) * math.sqrt(252.0))
    n = len(nav)
    d0 = pd.Timestamp(str(daily["date"].iloc[0]))
    d1 = pd.Timestamp(str(daily["date"].iloc[-1]))
    years_cal = (d1 - d0).days / 365.25
    cagr_cal = float((nav[-1] / float(nav0)) ** (1.0 / years_cal) - 1.0) if years_cal > 0 else float("nan")
    cagr_sess = float((nav[-1] / float(nav0)) ** (252.0 / n) - 1.0) if n else float("nan")
    return {
        "sessions": int(n),
        "years_calendar": years_cal,
        "cagr_calendar": cagr_cal,
        "cagr_252_per_session": cagr_sess,
        "vol_annual_252": vol,
        "max_drawdown_daily": mdd,
    }


def main(out_dir: str | Path = "evidence/probe-hold-kill") -> dict:
    out = Path(out_dir)
    ledger_dir = out / "ledgers"
    ledger_dir.mkdir(parents=True, exist_ok=True)

    recorded = json.loads(E3_SUMMARY.read_text(encoding="utf-8"))["cells"]["primary"]
    gate = {
        "static_nav_end": float(recorded["arms"]["static"]["nav_end"]),
        "static_n_fills": int(recorded["arms"]["static"]["n_fills"]),
        "static_head": recorded["arms"]["static"]["ledger_head"],
        "lots_nav_end": float(recorded["arms"]["lots"]["nav_end"]),
        "lots_head": recorded["arms"]["lots"]["ledger_head"],
        "lots_static_annual_cny": float(recorded["deltas"]["lots-static"]["annual_cny"]),
    }

    market = build_market("data/etf_bars.parquet", "data/corp_actions.parquet",
                          "evidence/sleeve_scores.parquet", start=START, end=END)
    codes = sorted(market.returns)
    slippage = slippage_table(market, codes, COST_MODE)

    results, arms, monthly = {}, {}, {}
    for name in ARMS_RUN:
        path = ledger_dir / f"nav50000_tol15.1_measured_{name}.jsonl"
        if path.exists():
            path.unlink()
        res = replay(market, ARMS[name], nav0=NAV0, tolerance_bp=TOLERANCE, cost_mode=COST_MODE,
                     ledger_path=path, start=START, end=END)
        results[name] = res
        stats = res.stats
        first = res.monthly.iloc[0]
        arms[name] = {
            "nav_end": float(stats["nav_end"]),
            "net_cny": float(stats["nav_end"]) - float(NAV0),
            "cagr_monthly_basis": float(stats["cagr"]),
            "vol_monthly_basis": float(stats["vol_annual"]),
            "max_drawdown_monthly": float(stats["max_drawdown"]),
            "n_fills": int(stats["n_fills"]),
            "n_fills_after_entry": int((res.fills["date"] != market.sessions[0]).sum()),
            "cost_bp_of_nav_per_year": float(stats["cost_bp_of_nav_per_year"]),
            "turnover_per_year": float(stats["turnover_per_year"]),
            "entry_cash_share": float(first["cash"] / first["nav"]),
            "entry": _entry_realisation(res, market, NAV0),
            "ledger_head": _head(path),
            **daily_metrics(res.daily, NAV0),
        }
        monthly[name] = res.monthly

    # ---- reproduction gate -------------------------------------------------
    checks = {
        "static_nav_end": abs(arms["static"]["nav_end"] - gate["static_nav_end"]) <= GATE_NAV_TOL,
        "static_n_fills": arms["static"]["n_fills"] == gate["static_n_fills"],
        "static_head": arms["static"]["ledger_head"] == gate["static_head"],
        "lots_nav_end": abs(arms["lots"]["nav_end"] - gate["lots_nav_end"]) <= GATE_NAV_TOL,
        "lots_head": arms["lots"]["ledger_head"] == gate["lots_head"],
    }
    deltas: dict[str, dict] = {}
    for left, right in (("lots", "static"), ("hold", "lots"), ("hold_lot", "lots"),
                        ("hold_deploy", "lots"), ("hold_deploy", "lots_deploy_na"),
                        ("hold_lot", "hold"), ("hold_deploy", "hold_lot"), ("hold", "static")):
        if left not in monthly or right not in monthly:
            continue
        deltas[f"{left}-{right}"] = _cny_block(_delta_series(monthly[right], monthly[left],
                                                            NAV0))
    checks["lots_static_annual_cny"] = (
        abs(deltas["lots-static"]["annual_cny"] - gate["lots_static_annual_cny"]) <= GATE_DELTA_TOL)
    gate_ok = all(checks.values())

    # ---- the pre-declared decision ----------------------------------------
    lots = arms["lots"]
    decisions = {}
    for name in HOLD_ARMS:
        a = arms[name]
        ratio = a["nav_end"] / lots["nav_end"]
        d_mdd = (a["max_drawdown_daily"] - lots["max_drawdown_daily"]) * 100.0
        d_vol = (a["vol_annual_252"] - lots["vol_annual_252"]) * 100.0
        pass_return = abs(ratio - 1.0) <= RETURN_TOL
        pass_mdd = d_mdd >= -RISK_TOL_PP
        pass_vol = d_vol <= RISK_TOL_PP
        decisions[name] = {
            "nav_end": a["nav_end"],
            "nav_ratio_vs_lots": ratio,
            "return_gap_pct_of_lots": (ratio - 1.0) * 100.0,
            "pass_return_2pct": bool(pass_return),
            "daily_maxdd": a["max_drawdown_daily"],
            "daily_maxdd_gap_pp": d_mdd,
            "pass_maxdd_1pp": bool(pass_mdd),
            "daily_vol": a["vol_annual_252"],
            "daily_vol_gap_pp": d_vol,
            "pass_vol_1pp": bool(pass_vol),
            "passes_both": bool(pass_return and pass_mdd and pass_vol),
            "verdict": ("no-evidence-of-retirement (1 of 12 starts; grid mandatory)"
                        if (pass_return and pass_mdd and pass_vol)
                        else "refutes-retirement-for-this-arm-at-this-start"),
        }

    summary = {
        "probe": "hold-kill-single-cell",
        "declared": {
            "RETURN_TOL": RETURN_TOL,
            "RISK_TOL_PP": RISK_TOL_PP,
            "rule": ("retirement only if every hold arm passes both clauses at all 12 entry "
                     "starts; a pass here is not retirement, a failure here is a local refutation"),
        },
        "window": {"start": START, "end": END},
        "cell": {"nav0": float(NAV0), "tolerance_bp": float(TOLERANCE), "cost_mode": COST_MODE},
        "gate": {"recorded": gate, "checks": checks, "ok": gate_ok,
                 "verdict": "control-reproduces-e3" if gate_ok else "invalid_experiment"},
        "arms": arms,
        "deltas": {k: {kk: v[kk] for kk in ("annual_cny", "annual_cny_lo", "annual_cny_hi",
                                            "cumulative_cny", "sd_monthly_cny",
                                            "mde_annual_cny", "by_year_cny")}
                   for k, v in deltas.items()},
        "decisions": decisions,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                     encoding="utf-8")
    (out / "report.md").write_text(_report(summary), encoding="utf-8")
    return summary


def _report(s: dict) -> str:
    a, d = s["arms"], s["deltas"]
    lines = [
        "# 单格 kill probe：买一次之后什么都不做，能不能复现整个账本",
        "",
        f"窗口 {s['window']['start']} .. {s['window']['end']}，资本 {s['cell']['nav0']:.0f}，"
        f"门槛 {s['cell']['tolerance_bp']} bp，费率 {s['cell']['cost_mode']}。",
        "",
        f"预注册常数：RETURN_TOL = {s['declared']['RETURN_TOL']:.0%}、RISK_TOL = "
        f"{s['declared']['RISK_TOL_PP']} pp（账本 seq 152）。",
        "",
        f"复现闸门：**{s['gate']['verdict']}**",
        "",
        "| 臂 | 终值净 CNY | 相对 lots | 日频 maxDD | 日频 vol | 成交 | 入场后成交 | 入场现金 | 成本 bp/yr |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, x in a.items():
        lines.append(
            f"| `{name}` | {x['nav_end']:,.2f} | {x['nav_end'] / a['lots']['nav_end'] - 1:+.2%} | "
            f"{x['max_drawdown_daily']:.2%} | {x['vol_annual_252']:.2%} | {x['n_fills']} | "
            f"{x['n_fills_after_entry']} | {x['entry_cash_share']:.2%} | "
            f"{x['cost_bp_of_nav_per_year']:.2f} |")
    lines += ["", "## 判定（预注册规则逐条）", ""]
    for name, v in s["decisions"].items():
        lines.append(
            f"- `{name}`：终值比 {v['nav_ratio_vs_lots']:.4f}（{v['return_gap_pct_of_lots']:+.2f}% of lots，"
            f"2% 带{'内' if v['pass_return_2pct'] else '外'}）；日频 maxDD 差 "
            f"{v['daily_maxdd_gap_pp']:+.2f} pp（{'过' if v['pass_maxdd_1pp'] else '不过'}）；日频 vol 差 "
            f"{v['daily_vol_gap_pp']:+.2f} pp（{'过' if v['pass_vol_1pp'] else '不过'}）→ **{v['verdict']}**")
    lines += ["", "## 差值的年度净 CNY（月度口径，与 E3 同一算术）", "",
              "| 对比 | 年化 CNY | 90% 区间 | MDE | 累计 CNY |", "|---|---|---|---|---|"]
    for k, v in d.items():
        lines.append(f"| `{k}` | {v['annual_cny']:,.2f} | [{v['annual_cny_lo']:,.2f}, "
                     f"{v['annual_cny_hi']:,.2f}] | {v['mde_annual_cny']:,.2f} | "
                     f"{v['cumulative_cny']:,.2f} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(json.dumps(main()["decisions"], indent=2, ensure_ascii=False))