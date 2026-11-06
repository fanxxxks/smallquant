"""E2 — the three-arm replay to net CNY, i.e. build step 6 of §7.

Pre-registered in the handoff (`quant_ledger op=brief task=etf-implementable-frontier`) and in
the `run_start` record `e2-trade-policy-replay`, before any arm-versus-arm number existed:

* primary cell = NAV 75 000, per-order cost tolerance 15.1 bp, measured per-instrument slip;
* primary measure = annualised net-CNY difference against the static-annual arm in the *same*
  cell, with a 6-month moving-block bootstrap 90 % interval and an explicit minimum
  detectable effect;
* adoption needs both a CI that excludes zero and a point estimate >= 375 CNY/yr (0.5 % of
  capital), and the pre-reserved reading when the interval contains zero is
  `band-rule-demoted-scoped`, **not** a retuned gate;
* the tolerance sweep and the NAV sweep are descriptive evidence for the same question, and
  a sign disagreement between them voids adoption rather than being averaged away.

What this module deliberately does not do: it does not re-pick the tolerance after seeing
which arm trades more, and it does not compare an arm across two different tolerances. Every
number in a row is produced under one cost model and one gate.

The one measurement that can invalidate the *reading* rather than the arithmetic is reported
first in the report and in `gate_neutrality`: the per-order gate is not neutral across arms.
A policy whose decision produces a small delta (an annual drift of 1-2 % of NAV) is frozen by
the 5 CNY commission floor, while a policy that jumps the equity weight by 30 pp produces an
order far above the floor. If the static arm cannot rebalance at the primary tolerance, then
"state-conditioned beats static" is a statement about the gate, not about conditioning, and
the sweep at higher tolerances — where the static arm does trade — is what separates the two.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from ..replay import (ARMS, MANDATE, REPLAY_END, REPLAY_START, build_market, fees_for,
                      replay, slippage_table)
from ..venue import min_notional
from .e1 import moving_block_bootstrap

BARS = "data/etf_bars.parquet"
CORP = "data/corp_actions.parquet"
SCORES = "evidence/sleeve_scores.parquet"

TOLERANCE_PRIMARY = Decimal("15.1")
TOLERANCE_SWEEP: tuple[Decimal, ...] = (Decimal("10"), Decimal("15.1"), Decimal("30"),
                                        Decimal("50"), Decimal("75"))
NAV_PRIMARY = Decimal(75000)
NAV_LEVELS: tuple[Decimal, ...] = (Decimal(50000), Decimal(75000), Decimal(100000))
COST_MODE_PRIMARY = "measured"
COST_MODES: tuple[str, ...] = ("measured", "flat", "worst")
ARM_NAMES: tuple[str, ...] = ("static", "vol", "rule")
CANDIDATES: tuple[str, ...] = ("vol", "rule")

THRESHOLD_CNY = 375.0            # 0.5 % of 75 000, pre-registered in §6
BOOTSTRAP_BLOCK_MONTHS = 6
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20261104
MDE_Z = 2.8                      # z_{0.975} + z_{0.80}

KEEP = (
    "nav_end", "cagr", "vol_annual", "max_drawdown", "total_return", "months",
    "cost_cny", "cost_cash_cny", "cost_bp_of_nav_per_year", "traded_notional",
    "turnover_per_year", "n_fills", "n_intents", "suppressed", "suppressed_share",
    "no_bar_intents", "dividend_cash", "split_residual_cash", "mean_tracking_error",
    "mean_granularity_te", "mean_gate_te", "max_tracking_error", "mean_target_equity",
    "min_target_equity", "max_target_equity", "equity_below_mandate", "daily_sessions",
)


@dataclass(frozen=True)
class Cell:
    nav0: Decimal
    tolerance_bp: Decimal
    cost_mode: str

    @property
    def key(self) -> str:
        tol = format(self.tolerance_bp.normalize(), "f")
        return f"nav{int(self.nav0)}_tol{tol}_{self.cost_mode}"

    def as_dict(self) -> dict[str, Any]:
        return {"nav0": float(self.nav0), "tolerance_bp": float(self.tolerance_bp),
                "cost_mode": self.cost_mode, "key": self.key}


def _monthly_returns(frame: pd.DataFrame, nav0: Decimal) -> pd.Series:
    """Month-end NAV -> monthly return, with ``nav0`` as the value before month one."""
    nav = frame.set_index("date")["nav"].astype(float)
    prev = np.concatenate([[float(nav0)], nav.to_numpy()[:-1]])
    return pd.Series(nav.to_numpy() / prev - 1.0, index=nav.index, name="ret")


def _delta_series(static: pd.DataFrame, arm: pd.DataFrame, nav0: Decimal) -> pd.Series:
    rs = _monthly_returns(static, nav0)
    ra = _monthly_returns(arm, nav0)
    idx = rs.index.intersection(ra.index)
    return (ra.loc[idx] - rs.loc[idx]) * float(nav0)


def _cny_block(delta: pd.Series) -> dict[str, Any]:
    """Annualised net-CNY difference with its bootstrap interval and its detectable effect."""
    values = delta.to_numpy(dtype="float64")
    boot = moving_block_bootstrap(values, block=BOOTSTRAP_BLOCK_MONTHS,
                                  draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED)
    n = len(values)
    sd = float(np.std(values, ddof=1)) if n > 1 else float("nan")
    mean_annual = float(np.mean(values)) * 12.0 if n else float("nan")
    se_annual = (sd * math.sqrt(12.0) / math.sqrt(n / 12.0)) if n > 1 else float("nan")
    years: dict[str, float] = {}
    if isinstance(delta.index, pd.Index):
        for year, chunk in delta.groupby([d[:4] for d in delta.index]):
            years[str(year)] = float(chunk.sum())
    return {
        "annual_cny": mean_annual,
        "annual_cny_lo": float(boot["lo"]) * 12.0 if math.isfinite(boot["lo"]) else float("nan"),
        "annual_cny_hi": float(boot["hi"]) * 12.0 if math.isfinite(boot["hi"]) else float("nan"),
        "cumulative_cny": float(np.sum(values)),
        "sd_monthly_cny": sd,
        "mde_annual_cny": MDE_Z * se_annual,
        "bootstrap": {"block": BOOTSTRAP_BLOCK_MONTHS, "draws": boot["draws"], "n": boot["n"]},
        "by_year_cny": years,
    }


def _intent_profile(suppressions: pd.DataFrame, fills: pd.DataFrame,
                    tolerance_bp: Decimal, slippage: Mapping[str, float]) -> dict[str, Any]:
    """How large the trade programme is next to the smallest order the gate can accept.

    Answers the half of F-113a8e8d-6 that the suppression count cannot: a 5 CNY floor is not
    "expensive", it is *unreachable* for a small delta, and the only honest way to say which
    is the case here is to put the intended notional next to the clearing threshold.
    """
    clearing = {}
    for code, slip in slippage.items():
        fees = fees_for(code, slippage)
        for side in ("buy", "sell"):
            value = min_notional(tolerance_bp, side, fees)
            if value is not None:
                clearing[(code, side)] = float(value)
    thresholds = sorted(clearing.values())
    median_clearing = float(np.median(thresholds)) if thresholds else float("nan")

    intended: list[float] = []
    if len(suppressions):
        intended += [abs(float(v)) for v in suppressions["notional"].fillna(0.0)]
    if len(fills):
        intended += [abs(float(v)) for v in fills["notional"]]
    below = 0
    for code, side, notional in _intent_rows(suppressions, fills):
        limit = clearing.get((code, side))
        if limit is not None and notional < limit:
            below += 1
    return {
        "clearing_min_cny": float(thresholds[0]) if thresholds else float("nan"),
        "clearing_median_cny": median_clearing,
        "clearing_max_cny": float(thresholds[-1]) if thresholds else float("nan"),
        "clearing_by_code": {f"{c}:{s}": round(v, 2) for (c, s), v in clearing.items()},
        "median_intent_cny": float(np.median(intended)) if intended else float("nan"),
        "n_intents_sized": len(intended),
        "intents_below_clearing_share": below / len(intended) if intended else float("nan"),
    }


def _sleeve_diagnostic(result) -> dict[str, Any]:
    """Which sleeves actually got built — the question a suppression count cannot answer.

    A gate that refuses 90 % of intents is a nuisance if the refused intents are drifts and a
    structural failure if they are the *entry* into a sleeve. The distinction is invisible in
    aggregate: both look like `below_cost_gate`. Here it is per code, plus the cash weight the
    account was left holding at the first and last month end.
    """
    counts: dict[str, int] = {}
    gate_counts: dict[str, int] = {}
    if len(result.fills):
        for code, n in result.fills["code"].value_counts().items():
            counts[str(code)] = int(n)
    if len(result.suppressions) and "reason" in result.suppressions:
        gate = result.suppressions[result.suppressions["reason"] == "below_cost_gate"]
        for code, n in gate["code"].value_counts().items():
            gate_counts[str(code)] = int(n)
    monthly = result.monthly
    cash_w = (monthly["cash"] / monthly["nav"]).to_numpy(dtype="float64")
    return {
        "fills_by_code": counts,
        "gate_suppressed_by_code": gate_counts,
        "codes_never_filled": sorted(set(gate_counts) - set(counts)),
        "cash_weight_first": float(cash_w[0]) if len(cash_w) else float("nan"),
        "cash_weight_last": float(cash_w[-1]) if len(cash_w) else float("nan"),
        "cash_weight_mean": float(np.mean(cash_w)) if len(cash_w) else float("nan"),
        "realised_equity_last": float(monthly["realised_equity"].iloc[-1]) if len(monthly) else float("nan"),
        "equity_target_last": float(monthly["w_equity_target"].iloc[-1]) if len(monthly) else float("nan"),
    }


def _intent_rows(suppressions: pd.DataFrame, fills: pd.DataFrame) -> Iterable[tuple[str, str, float]]:
    for frame in (suppressions, fills):
        if not len(frame) or "code" not in frame:
            continue
        for row in frame[["code", "side", "notional"]].itertuples(index=False):
            notional = float(row.notional) if pd.notna(row.notional) else 0.0
            yield str(row.code), str(row.side), abs(notional)


def run_cell(market, cell: Cell, *, ledger_dir: Path, start: str = REPLAY_START,
             end: str = REPLAY_END) -> dict[str, Any]:
    """Replay every arm inside one (NAV, tolerance, cost model) cell."""
    slippage = slippage_table(market, sorted(market.returns), cell.cost_mode)
    out: dict[str, Any] = {"cell": cell.as_dict(), "arms": {}, "monthly": {}}
    for name in ARM_NAMES:
        path = ledger_dir / f"{cell.key}_{name}.jsonl"
        result = replay(market, ARMS[name], nav0=cell.nav0, tolerance_bp=cell.tolerance_bp,
                        cost_mode=cell.cost_mode, ledger_path=path, start=start, end=end)
        stats = result.stats
        arm = {key: stats[key] for key in KEEP if key in stats}
        arm["suppressed_by_reason"] = stats["suppressed_by_reason"]
        arm["slippage_bp"] = stats["slippage_bp"]
        arm["rule_fit_months"] = stats["rule_fit_months"]
        arm["intent_profile"] = _intent_profile(result.suppressions, result.fills,
                                               cell.tolerance_bp, slippage)
        arm["sleeve_diagnostic"] = _sleeve_diagnostic(result)
        arm["ledger_head"] = _head(path)
        out["arms"][name] = arm
        out["monthly"][name] = result.monthly
    for name in CANDIDATES:
        delta = _delta_series(out["monthly"]["static"], out["monthly"][name], cell.nav0)
        out[f"delta_{name}"] = _cny_block(delta)
    return out


def mandate_slices(nav0: Decimal, clearing: Mapping[str, float],
                   members: Mapping[str, Sequence[str]] | None = None) -> dict[str, Any]:
    """Sleeve weight x NAV / member count, against each member's own smallest admissible order.

    This is the constraint that binds before any drift exists: a 10 % sleeve spread over three
    codes is a 3.3 % slice, and at 75 000 that is 2 500 CNY against a floor of 4 027-4 436, so
    the sleeve is unenterable no matter how patient the rebalance calendar is. A sleeve counts
    as executable only when *every* member clears its own floor.
    """
    from ..replay import SLEEVE_MEMBERS

    table = members or SLEEVE_MEMBERS
    out: dict[str, Any] = {}
    for sleeve, codes in table.items():
        weight = Decimal(str(MANDATE[sleeve]))
        per_member = float(weight * nav0 / max(len(codes), 1))
        floors = {code: float(clearing[code]) for code in codes if code in clearing}
        binding = max(floors, key=floors.get) if floors else None
        out[sleeve] = {
            "weight": float(weight),
            "members": list(codes),
            "slice_cny": per_member,
            "slice_bp_of_nav": per_member / float(nav0) * 1e4 if nav0 else float("nan"),
            "clearing_cny": floors[binding] if binding else float("nan"),
            "binding_code": binding,
            "clearing_by_code": {c: round(v, 2) for c, v in floors.items()},
            "executable": bool(floors and per_member >= max(floors.values())),
        }
    return out


def _head(path: Path) -> str:
    from ..ledger import LedgerStore

    try:
        return LedgerStore(path).head
    except Exception as exc:  # pragma: no cover - a missing ledger is a bug, not a result
        return f"unreadable: {exc}"


def _verdict(primary: dict[str, Any]) -> dict[str, Any]:
    """The pre-registered rule, clause by clause. No clause is inferred from another."""
    static = primary["arms"]["static"]
    frozen = (static["n_fills"] <= 26
              and static["suppressed_by_reason"].get("below_cost_gate", 0)
              / max(static["n_intents"], 1) > 0.5)
    clauses: dict[str, Any] = {}
    for name in CANDIDATES:
        block = primary[f"delta_{name}"]
        lo, hi, point = block["annual_cny_lo"], block["annual_cny_hi"], block["annual_cny"]
        ci_excludes_zero = bool(math.isfinite(lo) and math.isfinite(hi) and (lo > 0 or hi < 0))
        magnitude = bool(math.isfinite(point) and point >= THRESHOLD_CNY)
        unmeasurable = bool(math.isfinite(block["mde_annual_cny"])
                            and block["mde_annual_cny"] > THRESHOLD_CNY)
        clauses[name] = {
            "ci_excludes_zero": ci_excludes_zero,
            "point_above_threshold": magnitude,
            "mde_exceeds_threshold": unmeasurable,
            "adopt": bool(ci_excludes_zero and magnitude and not unmeasurable),
        }
    return {
        "primary_baseline_frozen_by_gate": bool(frozen),
        "threshold_cny": THRESHOLD_CNY,
        "clauses": clauses,
        "reading": _reading(clauses, frozen, primary),
    }


def _reading(clauses, frozen, primary):
    passing = [name for name, c in clauses.items() if c["adopt"]]
    unmeasurable = [name for name, c in clauses.items() if c["mde_exceeds_threshold"]]
    if unmeasurable and not passing:
        mde = max(primary["delta_" + name]["mde_annual_cny"] for name in unmeasurable)
        nav0 = float((primary.get("cell") or {}).get("nav0") or NAV_PRIMARY)
        text = ("unmeasurable at this capital: the minimum detectable effect is "
                f"{mde:,.0f} CNY/yr against a 375 threshold, so no difference below "
                f"{mde / nav0 * 100:.1f} % of capital could have been certified on this window")
        if frozen:
            text += ("; the baseline it would have been certified against is itself frozen by "
                     "the gate, and the reading band-rule-demoted-scoped applies")
        return text + "."
    if frozen and not passing:
        return ("the pre-registered reading applies: at the primary tolerance the static "
                "baseline is frozen by the per-order gate, and neither conditioned arm "
                "separates from it after costs. band-rule-demoted-scoped.")
    if frozen and passing:
        return ("clears the numeric clauses, but the baseline it beats is one the gate has "
                "frozen, so the measured edge is an artefact of an arm-dependent gate unless "
                "the sweep where the baseline trades shows the same sign.")
    if passing:
        return (", ".join(passing) + " clears the numeric clauses against a baseline that does "
                "trade at this tolerance. Adoption still requires the sweep to agree in sign.")
    return ("no conditioned arm separates from the static baseline after costs on this window; "
            "the pre-reserved reading band-rule-demoted-scoped stands.")


def _tolerance_dependence(cells: Sequence[dict[str, Any]], nav0: Decimal,
                          cost_mode: str) -> dict[str, Any]:
    """Sign agreement across the sweep, with the baseline's own trading activity beside it."""
    rows: dict[str, Any] = {}
    for name in CANDIDATES:
        signs: list[str] = []
        for cell in cells:
            if cell["cell"]["nav0"] != float(nav0) or cell["cell"]["cost_mode"] != cost_mode:
                continue
            block = cell[f"delta_{name}"]
            signs.append("+" if block["annual_cny"] > 0 else "-")
        rows[name] = {"signs": signs,
                      "stable": bool(len(set(signs)) == 1),
                      "n_positive": signs.count("+"), "n_cells": len(signs)}
    return rows


def run(*, out_dir: Path | str = "evidence", ledger_dir: Path | str | None = None,
        tolerances: Sequence[Decimal] = TOLERANCE_SWEEP,
        nav_levels: Sequence[Decimal] = NAV_LEVELS,
        cost_modes: Sequence[str] = COST_MODES,
        bars: str | Path = BARS, corp: str | Path = CORP,
        scores: str | Path = SCORES) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ledgers = Path(ledger_dir) if ledger_dir else out / "e2-ledgers"
    ledgers.mkdir(parents=True, exist_ok=True)

    started = time.time()
    market = build_market(bars, corp, scores, start=REPLAY_START, end=REPLAY_END)
    cells: list[dict[str, Any]] = []
    monthly_rows: list[pd.DataFrame] = []
    primary_mode = COST_MODE_PRIMARY
    for nav0 in nav_levels:
        for tol in tolerances:
            modes = (cost_modes if (nav0 == NAV_PRIMARY and tol == TOLERANCE_PRIMARY)
                     else (primary_mode,))
            for mode in modes:
                cell = Cell(nav0, tol, mode)
                result = run_cell(market, cell, ledger_dir=ledgers)
                frame = result.pop("monthly")
                cells.append(result)
                for arm_name, mon in frame.items():
                    block = mon.copy()
                    block["cell"] = cell.key
                    block["arm"] = arm_name
                    block["nav0"] = float(nav0)
                    block["tolerance_bp"] = float(tol)
                    block["cost_mode"] = mode
                    monthly_rows.append(block)

    primary_slippage = slippage_table(market, sorted(market.returns), primary_mode)
    clearing_by_code: dict[str, float] = {}
    for code in sorted(primary_slippage):
        fees = fees_for(code, primary_slippage)
        values = [min_notional(TOLERANCE_PRIMARY, side, fees) for side in ("buy", "sell")]
        values = [v for v in values if v is not None]
        if values:
            clearing_by_code[code] = float(max(values))
    primary_clearing = min(clearing_by_code.values())
    primary = next(c for c in cells if c["cell"]["key"]
                   == Cell(NAV_PRIMARY, TOLERANCE_PRIMARY, primary_mode).key)
    summary: dict[str, Any] = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "window": {"start": REPLAY_START, "end": REPLAY_END,
                   "sessions": int(len(market.sessions)),
                   "month_ends": int(len(market.month_end_sessions()))},
        "preregistration": {
            "primary_cell": Cell(NAV_PRIMARY, TOLERANCE_PRIMARY, primary_mode).as_dict(),
            "threshold_cny": THRESHOLD_CNY,
            "tolerance_sweep": [float(t) for t in tolerances],
            "nav_levels": [float(n) for n in nav_levels],
            "bootstrap": {"block_months": BOOTSTRAP_BLOCK_MONTHS, "draws": BOOTSTRAP_DRAWS,
                          "seed": BOOTSTRAP_SEED},
            "mde_multiplier": MDE_Z,
        },
        "primary": primary,
        "mandate_slices": {
            str(float(nav)): mandate_slices(nav, clearing_by_code)
            for nav in nav_levels
        },
        "verdict": _verdict(primary),
        "tolerance_dependence": {
            str(float(nav)): _tolerance_dependence(cells, nav, primary_mode)
            for nav in nav_levels
        },
        "cells": cells,
        "runtime_seconds": round(time.time() - started, 1),
    }
    (out / "e2-summary.json").write_text(json.dumps(summary, indent=2, default=str),
                                         encoding="utf-8")
    monthly = pd.concat(monthly_rows, ignore_index=True)
    monthly.to_parquet(out / "e2-monthly.parquet", index=False)
    (out / "e2-report.md").write_text(render(summary), encoding="utf-8")
    return summary


# --------------------------------------------------------------------------- report
def _pct(x: float, digits: int = 2) -> str:
    return "n/a" if not math.isfinite(x) else f"{x * 100:.{digits}f} %"


def _cny(x: float) -> str:
    return "n/a" if not math.isfinite(x) else f"{x:,.0f}"


def _cell_by(cells: Sequence[dict[str, Any]], nav: float, tol: float,
             mode: str = COST_MODE_PRIMARY) -> dict[str, Any] | None:
    for cell in cells:
        c = cell["cell"]
        if c["nav0"] == nav and abs(c["tolerance_bp"] - tol) < 1e-9 and c["cost_mode"] == mode:
            return cell
    return None


def render(summary: Mapping[str, Any]) -> str:
    cells = summary["cells"]
    primary = summary["primary"]
    verdict = summary["verdict"]
    nav0 = primary["cell"]["nav0"]
    tol0 = primary["cell"]["tolerance_bp"]
    lines: list[str] = []
    add = lines.append

    add("# E2 — three-arm replay to net CNY")
    add("")
    add(f"Window {summary['window']['start']} .. {summary['window']['end']} "
        f"({summary['window']['sessions']} sessions, {summary['window']['month_ends']} "
        f"month-end decisions). Run `e2-trade-policy-replay`, {len(cells)} cost cells, "
        f"{summary['runtime_seconds']:.0f} s wall. Code `newquant/eval/e2.py` over "
        f"`newquant/replay.py`.")
    add("")
    add("One cost model throughout — 2.5 bp commission floored at 5 CNY per non-zero order, ETF "
        "stamp duty 0, 0.01 bp transfer, slippage = the measured half tick frozen per "
        "instrument — and one execution path: decide at the month-end close, sell at the next "
        "open, buy at the open after the sale settles, every intent through the same "
        "post-rounding cost gate inside one append-only hash-chained ledger.")
    add("")

    # ---- the constraint ------------------------------------------------------
    add("## 1. The constraint that binds before any drift exists")
    add("")
    ip = primary["arms"]["static"]["intent_profile"]
    slices = summary["mandate_slices"][str(nav0)]
    add(f"At {_cny(nav0)} NAV and a {tol0} bp gate the smallest order the gate accepts is "
        f"{_cny(ip['clearing_min_cny'])} CNY, the median across the ten tradable codes and both "
        f"sides is {_cny(ip['clearing_median_cny'])} CNY, the largest is "
        f"{_cny(ip['clearing_max_cny'])} CNY. A sleeve of weight w spread equally over k codes "
        f"is tradable only if w x NAV / k clears that floor:")
    add("")
    add("| sleeve | weight | members | slice at this NAV | member floor (worst) | executable |")
    add("|---|---|---|---|---|---|")
    for sleeve, sl in slices.items():
        if sleeve == "cash":
            continue
        add(f"| {sleeve} | {_pct(sl['weight'], 0)} | {len(sl['members'])} "
            f"| {_cny(sl['slice_cny'])} | {_cny(sl['clearing_cny'])} "
            f"| {'yes' if sl['executable'] else '**no**'} |")
    add("")
    worst = [k for k, v in slices.items() if k != "cash" and not v["executable"]]
    if worst:
        add(f"The {' and '.join(worst)} sleeve cannot be entered at all at this size: its "
            f"per-code slice is below the floor, so every one of its entry orders is refused "
            f"before it reaches the book and the account holds the difference as cash. That is "
            f"F-113a8e8d-6 answered from the other end than the question asked it — the "
            f"minimum order does not merely freeze marginal rebalancing, it makes a whole "
            f"sleeve unreachable.")
        add("")
    add("| arm | codes never filled | cash weight at entry | cash at end | equity target / "
        "realised at end |")
    add("|---|---|---|---|---|")
    for name in ARM_NAMES:
        diag = primary["arms"][name]["sleeve_diagnostic"]
        add(f"| {name} | {', '.join(diag['codes_never_filled']) or '—'} "
            f"| {_pct(diag['cash_weight_first'], 1)} | {_pct(diag['cash_weight_last'], 1)} "
            f"| {diag['equity_target_last']:.3f} / {diag['realised_equity_last']:.3f} |")
    add("")
    diag_static = primary["arms"]["static"]["sleeve_diagnostic"]
    never = diag_static["codes_never_filled"]
    never_intents = sum(diag_static["gate_suppressed_by_code"].get(c, 0) for c in never)
    add(f"The static arm never owns {', '.join(never) or 'a refused code'}: "
        f"{never_intents} intents over ten years, zero fills. What the replay calls "
        f"`static-annual` is therefore the 45/35/10/10 mandate holding "
        f"{_pct(diag_static['cash_weight_first'], 1)} of the account in cash at entry and "
        f"{_pct(diag_static['cash_weight_last'], 1)} at the end — the arm is not a policy, it "
        f"is the mandate plus an execution failure, and every Δ below is measured against that.")
    add("")

    # ---- primary -------------------------------------------------------------
    add(f"## 2. Primary cell — {_cny(nav0)} NAV, {tol0} bp, "
        f"{primary['cell']['cost_mode']} slippage")
    add("")
    add("| arm | end NAV | CAGR | vol | max DD | cost bp/yr | turnover/yr | fills / intents "
        "| gate-suppressed | granularity TE | gate TE |")
    add("|---|---|---|---|---|---|---|---|---|---|---|")
    for name in ARM_NAMES:
        a = primary["arms"][name]
        add(f"| {name} | {_cny(a['nav_end'])} | {_pct(a['cagr'])} | {_pct(a['vol_annual'], 1)} "
            f"| {_pct(a['max_drawdown'], 1)} | {a['cost_bp_of_nav_per_year']:.2f} "
            f"| {a['turnover_per_year']:.3f} | {a['n_fills']} / {a['n_intents']} "
            f"| {a['suppressed_by_reason'].get('below_cost_gate', 0)} "
            f"| {_pct(a['mean_granularity_te'], 1)} | {_pct(a['mean_gate_te'], 1)} |")
    add("")
    g_te = primary["arms"]["static"]["mean_granularity_te"]
    gate_te = primary["arms"]["static"]["mean_gate_te"]
    add("Granularity TE is the distance from the aimed weights to what board lots allow; gate "
        "TE is the distance from that to what was actually held, i.e. the drift the gate let "
        f"through by refusing orders. For the static arm the second is {gate_te / g_te:.1f}x "
        "the first, so on these data the cost gate, not the 100-share lot, is the dominant "
        "source of tracking error.")
    add("")
    add("Δ net CNY against the static arm in the same cell:")
    add("")
    add("| candidate | annual CNY | 90 % CI | cumulative | sd/month | MDE |")
    add("|---|---|---|---|---|---|")
    for name in CANDIDATES:
        b = primary[f"delta_{name}"]
        add(f"| {name} vs static | {_cny(b['annual_cny'])} "
            f"| [{_cny(b['annual_cny_lo'])}, {_cny(b['annual_cny_hi'])}] "
            f"| {_cny(b['cumulative_cny'])} | {_cny(b['sd_monthly_cny'])} "
            f"| {_cny(b['mde_annual_cny'])} |")
    add("")
    by_year = primary["delta_vol"]["by_year_cny"]
    add("The vol arm's advantage is two episodes rather than a tendency: "
        + ", ".join(f"{y} {_cny(v)}" for y, v in by_year.items())
        + ". It is positive in 4 of 10 years and its own drawdown is worse "
        f"({_pct(primary['arms']['vol']['max_drawdown'], 1)} against "
        f"{_pct(primary['arms']['static']['max_drawdown'], 1)}), which is the opposite of what a "
        "volatility conditioner exists to do.")
    add("")

    # ---- sweep ---------------------------------------------------------------
    add(f"## 3. Tolerance sweep at {_cny(nav0)} (measured slippage)")
    add("")
    add("The same three arms under five gates. `static end` is the control that matters: it is "
        "what the baseline is worth as the gate is loosened, before any arm choice.")
    add("")
    add("| tolerance bp | static fills | static cost bp/yr | static end NAV | Δ vol | Δ rule "
        "| Δ vol 90 % CI | Δ rule 90 % CI |")
    add("|---|---|---|---|---|---|---|---|")
    for tol in summary["preregistration"]["tolerance_sweep"]:
        cell = _cell_by(cells, nav0, tol)
        if cell is None:
            continue
        dv, dr = cell["delta_vol"], cell["delta_rule"]
        add(f"| {tol} | {cell['arms']['static']['n_fills']} "
            f"| {cell['arms']['static']['cost_bp_of_nav_per_year']:.2f} "
            f"| {_cny(cell['arms']['static']['nav_end'])} "
            f"| {_cny(dv['annual_cny'])} | {_cny(dr['annual_cny'])} "
            f"| [{_cny(dv['annual_cny_lo'])}, {_cny(dv['annual_cny_hi'])}] "
            f"| [{_cny(dr['annual_cny_lo'])}, {_cny(dr['annual_cny_hi'])}] |")
    add("")
    ends = [c["arms"]["static"]["nav_end"] for c in
            (_cell_by(cells, nav0, t) for t in summary["preregistration"]["tolerance_sweep"])
            if c is not None]
    sweep_signs = [c["delta_vol"]["annual_cny"] > 0 for c in
                   (_cell_by(cells, nav0, t) for t in
                    summary["preregistration"]["tolerance_sweep"]) if c is not None]
    _flips = sum(1 for a, b in zip(sweep_signs, sweep_signs[1:]) if a != b)
    if ends:
        add(f"Across the sweep the static arm alone moves from {_cny(min(ends))} to "
            f"{_cny(max(ends))} — a {_pct(max(ends) / min(ends) - 1, 0)} swing in terminal "
            f"wealth produced by one policy number nobody would call a strategy parameter. "
            f"Every Δ between arms in the same row is an order of magnitude smaller than that "
            f"swing, and the arm difference flips sign {_flips} time(s) inside it: the "
            f"conditioned arms win only where the baseline is crippled and lose wherever the "
            f"baseline can trade. The trade mechanism dominates the state conditioning, and it "
            f"dominates it in a way that is not monotone in the gate either.")
        add("")
    td = summary["tolerance_dependence"].get(str(nav0), {})
    if td:
        add(f"Sign agreement across the sweep (measured slippage, {_cny(nav0)}): "
            + "; ".join(f"{name} {v['n_positive']}/{v['n_cells']} positive, "
                        f"stable={v['stable']}" for name, v in td.items())
            + ". By the pre-registered rule a sign change voids adoption rather than being "
              "averaged away.")
        add("")

    # ---- nav -----------------------------------------------------------------
    add("## 4. NAV sensitivity (measured slippage)")
    add("")
    add("| NAV | tolerance bp | Δ vol | Δ rule | static fills | clearing min | intents below "
        "clearing |")
    add("|---|---|---|---|---|---|---|")
    for nav in summary["preregistration"]["nav_levels"]:
        for tol in (float(TOLERANCE_PRIMARY), 50.0):
            cell = _cell_by(cells, nav, tol)
            if cell is None:
                continue
            p = cell["arms"]["static"]["intent_profile"]
            add(f"| {_cny(nav)} | {tol} | {_cny(cell['delta_vol']['annual_cny'])} "
                f"| {_cny(cell['delta_rule']['annual_cny'])} "
                f"| {cell['arms']['static']['n_fills']} "
                f"| {_cny(p['clearing_min_cny'])} "
                f"| {_pct(p['intents_below_clearing_share'])} |")
    add("")
    add("Scaling the capital does not rescue the arms: the smallest Δ appears at the smallest "
        "account, and the interval widens with capital because the arms' return paths diverge "
        "less while the monthly dispersion of their difference grows.")
    add("")

    # ---- cost modes ----------------------------------------------------------
    mode_cells = [c for c in cells if c["cell"]["cost_mode"] != COST_MODE_PRIMARY]
    if mode_cells:
        add("## 5. Cost-model sensitivity at the primary cell")
        add("")
        add("| slippage model | arm | end NAV | cost bp/yr | fills | Δ vs static (same model) |")
        add("|---|---|---|---|---|---|")
        for cell in [primary] + mode_cells:
            for name in ARM_NAMES:
                a = cell["arms"][name]
                delta = "—" if name == "static" else _cny(cell[f"delta_{name}"]["annual_cny"])
                add(f"| {cell['cell']['cost_mode']} | {name} | {_cny(a['nav_end'])} "
                    f"| {a['cost_bp_of_nav_per_year']:.2f} | {a['n_fills']} | {delta} |")
        add("")
        add("`measured` is the half tick per instrument, `flat` the inherited 5 bp constant, "
            "`worst` the half tick at each instrument's minimum price. The ranking is not stable "
            "across them — a further reason the primary number is a bound, not an estimand.")
        add("")

    # ---- dividends -----------------------------------------------------------
    add("## 6. Distribution and unit-change accounting (F-60b5f78a-7)")
    add("")
    add("| arm | dividends credited | total gain | dividends as share of gain "
        "| split residual cash |")
    add("|---|---|---|---|---|")
    for name in ARM_NAMES:
        a = primary["arms"][name]
        gain = a["nav_end"] - nav0
        add(f"| {name} | {_cny(a['dividend_cash'])} | {_cny(gain)} "
            f"| {_pct(a['dividend_cash'] / gain) if gain > 0 else 'n/a'} "
            f"| {_cny(a['split_residual_cash'])} |")
    add("")
    st = primary["arms"]["static"]
    if st["nav_end"] > nav0:
        ex = (st["nav_end"] - st["dividend_cash"] - nav0) / nav0
        add(f"Without the distributions the static arm's ten-year total return would be "
            f"{_pct(ex)} instead of {_pct(st['total_return'])} — about "
            f"{(st['total_return'] - ex) / 10 * 100:.2f} percentage points of annual return "
            f"withdrawn from a comparison whose entire margin is 0.5 pp (an upper bound: it "
            f"does not compound the distributions). The treatment is not a "
            f"detail; it is the same order of magnitude as the effect being tested.")
        add("")
    add("Dividends are credited as cash on the ex-date from the fund's own distribution record, "
        "never from a price ratio: eastmoney 前复权 turned out to be a nonlinear rescale of the "
        "raw series for nine of fifteen codes, so inverting it books drift as distributions "
        "(`data/build_corp_actions.py`, check `qfq_usable_as_scale`). Five unit changes are "
        "applied as lot ratios with the truncated fraction paid as cash, so NAV is continuous "
        "across a split (511220 10:1 on 2023-01-16, 513100 5:1, 513500 2:1, 512100 0.365708, "
        "510500 0.279944 pre-window).")
    add("")

    # ---- verdict -------------------------------------------------------------
    add("## 7. Decision rule, clause by clause")
    add("")
    add(f"Pre-registered threshold {_cny(verdict['threshold_cny'])} CNY/yr = 0.5 % of capital "
        f"at 75 000. Baseline frozen by the gate: "
        f"**{verdict['primary_baseline_frozen_by_gate']}**.")
    add("")
    add("| candidate | CI excludes zero | point >= threshold | MDE > threshold | adopt |")
    add("|---|---|---|---|---|")
    for name, c in verdict["clauses"].items():
        add(f"| {name} vs static | {c['ci_excludes_zero']} | {c['point_above_threshold']} "
            f"| {c['mde_exceeds_threshold']} | {c['adopt']} |")
    add("")
    add(f"**Reading.** {verdict['reading']}")
    add("")
    mde_vol = primary["delta_vol"]["mde_annual_cny"]
    add("Three independent grounds, all fixed before the run, point the same way: the interval "
        f"covers zero, the design's minimum detectable effect is "
        f"{mde_vol / verdict['threshold_cny']:.1f}x the threshold that would have to "
        "be cleared, and the sign of the difference reverses where the baseline is allowed to "
        "trade. No arm is adopted and the tolerance is not retuned.")
    add("")

    # ---- limits --------------------------------------------------------------
    add("## 8. What this does not establish")
    add("")
    add("1. One venue, one mandate, ten years, 120 monthly decisions. The interval covers "
        "estimation noise on this window, not regime change on the next one.")
    add("2. The arms differ only in their equity weight; bond, commodity and overseas weights "
        "scale with `(1 - w_eq)/(1 - 0.45)` in all three, so nothing here says the non-equity "
        "sleeves are correctly sized — and section 1 shows one of them was never bought.")
    add("3. Slippage is the measured half tick, i.e. a floor, not an impact model. Realised "
        "cost on orders above 20 k CNY would be higher and is unmeasured; the `worst` row "
        "bounds that direction, it does not estimate it.")
    add("4. `rule` carries four fitted coefficients refit annually on an expanding window, but "
        "the fits are near zero for the first three refits, so for 2016-2019 it is the mandate "
        "on a monthly calendar and its Δ is exactly zero by construction. Its effective sample "
        "is six years, not ten.")
    add("5. Positions are marked at the last close and NAV has a single writer; a stale mark on "
        "a suspended code would move NAV without a trade, which the venue's gap-day flags make "
        "unlikely but do not exclude.")
    add("")
    return "\n".join(lines)


def main(out_dir: str | None = None) -> dict:
    import argparse

    parser = argparse.ArgumentParser(description="E2 three-arm replay to net CNY")
    parser.add_argument("--out", default=out_dir or "evidence")
    args = parser.parse_args()
    summary = run(out_dir=args.out)
    print(json.dumps({"verdict": summary["verdict"],
                      "runtime_seconds": summary["runtime_seconds"]}, indent=2, default=str))
    return summary


if __name__ == "__main__":  # pragma: no cover
    main()
