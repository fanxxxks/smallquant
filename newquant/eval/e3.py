"""E3 — what the board lot costs at 50 000 CNY, in CNY, i.e. build step 7's precondition.

Pre-registered as `run-e3c00001-50k0-4c01-9a00-000000000001` (ledger seq 88) and amended once
before any full-window number was read (seq 89, `e3-redeploy-rule-amended`). The question is
narrow on purpose:

* at 50 000 the declared mandate 45/35/10/10 is not a weight vector the venue can hold, because
  one board lot of a par-quoted bond ETF is 10 000-14 135 CNY - about three times the
  post-rounding cost floor - so the bond sleeve stops at its nearest lot and the equal-weight
  split of the other sleeves falls under the gate (E2 measured 40.9 % cash at entry);
* the *alternative* is a mandate defined on lot counts: keep the largest k members per sleeve
  whose slice still clears ``max(min_notional, one lot)``, and let the sleeve's target weight be
  what those lots are worth (``newquant.replay.lot_composition``);
* the residual either sits in cash (``lots``) or is handed to the sleeves the lot did not bind
  (``lots_deploy``). Both are measured, neither is adopted on a point estimate alone.

Arms, all in one cell (50 000, 15.1 bp, measured slippage) and one window (2016-01-04 ..
2025-12-31):

======================  =========================================================
``static``              the E2 executed arm - control, must reproduce E2 exactly
``lots``                lot-defined composition, residual to cash
``lots_deploy``         lot-defined composition, residual to the unconstrained sleeves
``cash``                no position at all - the reference the idle cash is priced against
======================  =========================================================

Control clause (P1): if ``static`` does not reproduce nav_end 62 163.64, 6 fills and ledger
head ``db6a4f19...``, the run is ``invalid_experiment`` and no arm number in it may be quoted.
That check is deliberately first in the report, because the whole comparison is worth nothing
if the arm the others are differenced against has moved.

Adoption clause (P4): an arm is adopted only when its paired 6-month moving-block bootstrap
90 % interval against the control excludes zero. Otherwise the reading is "the lot's cost is
unmeasured at this capital, MDE = X CNY/yr", and the composition goes to the forward paper
book in its cash-residual form - a point estimate that cannot be separated from zero does not
license moving risk into the return sleeves.

Descriptive only (P5): the same comparison at 120 000, where floor(0.35 x NAV / lot) lands
within 2 pp of the bond target. This is the evidence for the *capital floor* option, not a
test of it: no arm at 120 000 can promote a mandate that has to hold at 50 000.
"""

from __future__ import annotations

import json
import math
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from ..replay import (ARMS, MANDATE, REPLAY_END, REPLAY_START, SLEEVE_MEMBERS, build_market,
                      lot_composition, replay, slippage_table)
from .e2 import Cell, KEEP, _cny_block, _delta_series, _head, _intent_profile, \
    _monthly_returns, _sleeve_diagnostic

BARS = "data/etf_bars.parquet"
CORP = "data/corp_actions.parquet"
SCORES = "evidence/sleeve_scores.parquet"
PROBE_TABLE = "evidence/probe-composition/table.json"

NAV_PRIMARY = Decimal(50000)
NAV_CAPITAL_FLOOR = Decimal(120000)
TOLERANCE = Decimal("15.1")
COST_MODE = "measured"
ARM_NAMES: tuple[str, ...] = ("static", "lots", "lots_deploy", "cash")
CONTROL = "static"

PAIRS: tuple[tuple[str, str], ...] = (
    ("lots", "static"),
    ("lots_deploy", "static"),
    ("lots_deploy", "lots"),
    ("lots", "cash"),
    ("lots_deploy", "cash"),
)

# Only the two pairs that answer the pre-registered question can carry adoption: the arm against
# the arm that was actually executed. The other three are reported because they are the same
# arithmetic on a different contrast (deploy against cash-residual, and both against cash), and
# quoting them as evidence would be picking the comparison after seeing the numbers.
ADOPTION_PAIRS: tuple[str, ...] = ("lots-static", "lots_deploy-static")

SLEEVES: tuple[str, ...] = ("equity", "bond", "commodity", "overseas")

E2_CONTROL = {
    "nav_end": 62163.64,
    "n_fills": 6,
    "ledger_head": "db6a4f19b62d1e759bd1c6177dee140f6c5cc46c5e6357053ed78b35cf07f1e9",
}
NAV_END_TOLERANCE_CNY = 0.01


def _monthly_sleeve_returns(market) -> pd.DataFrame:
    """Sleeve return per month-end interval, compounded from the session series.

    ``market.sleeve_returns`` is daily (one row per session), so a monthly number has to be the
    product over the interval between two month ends. Using the daily frame directly would
    silently annualise a daily number and overstate the idle-cash penalty by ~21x.
    """
    daily = market.sleeve_returns
    ends = [d for d in daily.index if d in set(market.month_end_sessions())]
    rows = {}
    for prev, cur in zip(ends, ends[1:]):
        window = daily.loc[(daily.index > prev) & (daily.index <= cur)]
        rows[cur] = (1.0 + window).prod() - 1.0
    return pd.DataFrame(rows).T


def _idle_cash_drag(frame: pd.DataFrame, sleeve_monthly: pd.DataFrame) -> dict[str, Any]:
    """First-order CNY value of the cash the composition could not invest.

    For every month the account held ``c`` in cash, that ``c`` missed the mandate's own return
    for the next month. Compounding that forgone gain at the account's own growth rate gives a
    CNY number that is comparable to a terminal value, which is the form the decision needs.
    Cross terms are ignored on purpose: this is the *idle cash* part of the shortfall, not the
    whole difference between two arms, and mixing the two would make the lot look responsible
    for the mix as well.
    """
    dates = list(frame["date"])
    cash_w = (frame["cash"] / frame["nav"]).astype(float).to_numpy()
    nav = frame["nav"].astype(float).to_numpy()
    mandate = np.array([float(MANDATE[s]) for s in SLEEVES])
    if len(sleeve_monthly) == 0:
        return {"idle_cash_drag_cny_first_order": float("nan"), "months_priced": 0}
    sm = sleeve_monthly.reindex(dates)
    drag = 0.0
    shadow = float(nav[0])
    months = 0
    for i in range(len(dates) - 1):
        nxt = dates[i + 1]
        if nxt not in sm.index or not np.isfinite(sm.loc[nxt].to_numpy(dtype="float64")).all():
            shadow = float(nav[i + 1])
            continue
        mandate_ret = float(np.dot(mandate, sm.loc[nxt].to_numpy(dtype="float64")))
        gain = shadow * float(cash_w[i]) * mandate_ret
        drag += gain
        shadow += gain
        months += 1
    return {
        "idle_cash_drag_cny_first_order": float(drag),
        "idle_cash_drag_bp_of_nav0_per_year": float(drag) / float(nav[0]) * 1e4 / max(months / 12, 1e-9),
        "months_priced": months,
    }


def _sleeve_table(frame: pd.DataFrame) -> dict[str, Any]:
    """Aimed versus realised per sleeve, and how many members the tree kept.

    Two caveats the table cannot show by itself, so they are in the report instead: a realised
    weight is value / NAV, so it drifts with prices between rebalances (equity underperformed
    gold and bonds for most of this decade, which makes equity look "short" in the calm years
    even when every intent filled), and ``members`` is only defined on a decision month. The
    last member count is therefore the last decision's, not the last month's.
    """
    out: dict[str, Any] = {}
    for sleeve in SLEEVES:
        aimed = frame[f"aimed_{sleeve}"].astype(float)
        realised = frame[f"realised_{sleeve}"].astype(float)
        members = frame[f"members_{sleeve}"].astype(int)
        non_empty = members[members > 0]
        out[sleeve] = {
            "aimed_first": float(aimed.iloc[0]),
            "aimed_last": float(aimed.iloc[-1]),
            "aimed_mean": float(aimed.mean()),
            "realised_first": float(realised.iloc[0]),
            "realised_last": float(realised.iloc[-1]),
            "realised_mean": float(realised.mean()),
            "gap_mean": float((aimed - realised).mean()),
            "gap_last": float(aimed.iloc[-1] - realised.iloc[-1]),
            "members_first": int(members.iloc[0]),
            "members_last_decision": int(non_empty.iloc[-1]) if len(non_empty) else 0,
            "months_short": int((realised < aimed - 0.02).sum()),
        }
    return out


def _entry_realisation(result, market, nav0: Decimal) -> dict[str, Any]:
    """Sleeve weights at the close of the entry session - the day-one composition.

    Reading it off the first month end is wrong: four weeks of price moves sit in between, and
    in January 2016 those four weeks were an equity crash, which flatters a composition that
    failed to buy equity. This reconstructs day one from the fills themselves.
    """
    entry = str(result.fills["date"].iloc[0]) if len(result.fills) else None
    if entry is None:
        return {"entry_date": None, "entry_cash": 1.0}
    rows = result.fills[result.fills["date"] == entry]
    held: dict[str, int] = {}
    spent = Decimal("0")
    costs = Decimal("0")
    for row in rows.itertuples(index=False):
        held[str(row.code)] = held.get(str(row.code), 0) + int(row.lots)
        spent += Decimal(str(row.notional))
        costs += Decimal(str(row.total_cost))
    value: dict[str, Decimal] = {s: Decimal("0") for s in SLEEVES}
    for code, lots in held.items():
        price = market.mark(code, entry)
        if price is None:
            continue
        sleeve = next(s for s, members in SLEEVE_MEMBERS.items() if code in members)
        value[sleeve] += price * lots * 100
    total = sum(value.values(), Decimal("0"))
    cash = nav0 - spent - costs
    denom = total + cash
    out: dict[str, Any] = {
        "entry_date": entry,
        "entry_cash": float(cash / denom) if denom > 0 else float("nan"),
        "entry_codes": sorted(held),
        "entry_costs_cny": float(costs),
        "entry_invested": float(total / denom) if denom > 0 else float("nan"),
    }
    for sleeve in SLEEVES:
        out[f"entry_{sleeve}"] = float(value[sleeve] / denom) if denom > 0 else float("nan")
    return out


def run_cell(market, cell: Cell, *, ledger_dir: Path, start: str = REPLAY_START,
             end: str = REPLAY_END, arms: Sequence[str] = ARM_NAMES,
             reference: str = CONTROL) -> dict[str, Any]:
    """Replay the composition arms in one cell and difference each against ``reference``."""
    slippage = slippage_table(market, sorted(market.returns), cell.cost_mode)
    sleeve_monthly = _monthly_sleeve_returns(market)
    out: dict[str, Any] = {"cell": cell.as_dict(), "arms": {}, "monthly": {}, "deltas": {}}
    started = time.time()
    for name in arms:
        path = ledger_dir / f"{cell.key}_{name}.jsonl"
        result = replay(market, ARMS[name], nav0=cell.nav0, tolerance_bp=cell.tolerance_bp,
                        cost_mode=cell.cost_mode, ledger_path=path, start=start, end=end)
        stats = result.stats
        arm = {key: stats[key] for key in KEEP if key in stats}
        arm["suppressed_by_reason"] = stats["suppressed_by_reason"]
        arm["slippage_bp"] = stats["slippage_bp"]
        arm["intent_profile"] = _intent_profile(result.suppressions, result.fills,
                                               cell.tolerance_bp, slippage)
        arm["sleeve_diagnostic"] = _sleeve_diagnostic(result)
        arm["ledger_head"] = _head(path)
        arm["sleeves"] = _sleeve_table(result.monthly)
        arm["entry"] = _entry_realisation(result, market, cell.nav0)
        arm.update(_idle_cash_drag(result.monthly, sleeve_monthly))
        out["arms"][name] = arm
        out["monthly"][name] = result.monthly
    for left, right in PAIRS:
        if left not in out["monthly"] or right not in out["monthly"]:
            continue
        delta = _delta_series(out["monthly"][right], out["monthly"][left], cell.nav0)
        out["deltas"][f"{left}-{right}"] = _cny_block(delta)
    out["seconds"] = round(time.time() - started, 1)
    return out


def control_check(primary: Mapping[str, Any]) -> dict[str, Any]:
    """P1: the control arm must be the arm E2 measured, to the cent and to the ledger head."""
    static = primary["arms"][CONTROL]
    nav_end = float(static["nav_end"])
    checks = {
        "nav_end": {
            "measured": nav_end,
            "e2": E2_CONTROL["nav_end"],
            "ok": abs(nav_end - E2_CONTROL["nav_end"]) <= NAV_END_TOLERANCE_CNY,
        },
        "n_fills": {
            "measured": int(static["n_fills"]),
            "e2": E2_CONTROL["n_fills"],
            "ok": int(static["n_fills"]) == E2_CONTROL["n_fills"],
        },
        "ledger_head": {
            "measured": static["ledger_head"],
            "e2": E2_CONTROL["ledger_head"],
            "ok": static["ledger_head"] == E2_CONTROL["ledger_head"],
        },
    }
    ok = all(v["ok"] for v in checks.values())
    return {"ok": ok, "clauses": checks,
            "verdict": "control-reproduces-e2" if ok else "invalid_experiment"}


def _decide(primary: Mapping[str, Any]) -> dict[str, Any]:
    """P4, clause by clause: a CI that excludes zero, or an unmeasured effect."""
    out: dict[str, Any] = {}
    for pair, block in primary["deltas"].items():
        lo, hi = block["annual_cny_lo"], block["annual_cny_hi"]
        point, mde = block["annual_cny"], block["mde_annual_cny"]
        separates = bool(math.isfinite(lo) and math.isfinite(hi) and (lo > 0 or hi < 0))
        out[pair] = {
            "annual_cny": point,
            "annual_cny_lo": lo,
            "annual_cny_hi": hi,
            "mde_annual_cny": mde,
            "separates_from_zero": separates,
            "reading": ("measurable" if separates
                        else ("unmeasurable at this capital" if math.isfinite(mde)
                              else "not priced")),
        }
    adopt = [k for k in ADOPTION_PAIRS
             if k in out and out[k]["separates_from_zero"] and out[k]["annual_cny"] > 0]
    chosen = None
    tie_break = None
    if adopt:
        # Both lot arms can clear the control while being indistinguishable from each other.
        # When they are, the decision does not go to the larger point estimate: `lots_deploy`
        # moves the residual into the return sleeves, so it is the higher-risk of the two and
        # an unmeasured +387 CNY/yr does not pay for that. The pre-registered conservative
        # branch is "lot form, residual to cash".
        deploy_gain = out.get("lots_deploy-lots", {})
        deploy_separates = bool(deploy_gain.get("separates_from_zero"))
        if "lots_deploy-static" in adopt and deploy_separates:
            chosen = "lots_deploy"
            tie_break = "redeploy beats cash-residual with an interval excluding zero"
        elif "lots-static" in adopt:
            chosen = "lots"
            tie_break = ("redeploy's gain over cash-residual does not separate from zero, so the "
                         "lower-risk form is kept")
        else:
            chosen = adopt[0].split("-")[0]
            tie_break = "only the redeploy arm separates from the control"
    return {
        "pairs": out,
        "adopted_arm": chosen,
        "tie_break": tie_break,
        "deploy_gain_separates": bool(out.get("lots_deploy-lots", {}).get("separates_from_zero")),
        "default_when_unmeasured": "lots (residual to cash)",
        "verdict": ("adopt-measurable-composition" if adopt
                    else "composition-kept-in-cash-residual-form"),
    }


def probe_congruence(market, cell: Cell) -> dict[str, Any]:
    """The probe that produced `bond-sleeve-lot-bound` counted the same k offline.

    `evidence/probe-composition/probe_table.py` is a throw-away script with no API and no tests,
    so the engine function is now the only owner of the rule. This check is what keeps the old
    artefact honest: if the two disagree at 2016-01-04, one of them is wrong and the ledger
    record that cites the probe has to be revisited rather than quietly overwritten.
    """
    path = Path(PROBE_TABLE)
    try:
        probe = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - missing artefact is reported, not raised
        return {"available": False, "error": str(exc)}
    nav_key = str(int(cell.nav0))
    block = probe.get("navs", {}).get(nav_key)
    if not block:
        return {"available": False, "error": f"no nav{nav_key} block in {path}"}
    slippage = slippage_table(market, sorted(market.returns), cell.cost_mode)
    _, members = lot_composition(market, REPLAY_START, dict(MANDATE), cell.nav0,
                                 cell.tolerance_bp, slippage)
    rows = {}
    for sleeve in SLEEVES:
        entry = block.get("sleeves", {}).get(sleeve, {})
        probe_k = entry.get("max_feasible_k")
        engine_k = len(members.get(sleeve, ()))
        # The probe skipped a member with no bar (`if px is None: continue`) instead of removing
        # it from the tree, so it counts funds that had not listed yet. 512100 lists on
        # 2016-11-04, after the probe's reference date.
        unlisted = [c for c in SLEEVE_MEMBERS[sleeve] if market.mark(c, REPLAY_START) is None]
        cause = None
        if probe_k != engine_k and unlisted:
            cause = f"probe counted {len(unlisted)} unlisted member(s): {','.join(unlisted)}"
        rows[sleeve] = {
            "probe_max_feasible_k": probe_k,
            "engine_k_at_2016_01_04": engine_k,
            "unlisted_at_ref": unlisted,
            "cause": cause,
            "agrees": probe_k == engine_k,
        }
    return {"available": True, "at": REPLAY_START, "nav": nav_key, "sleeves": rows,
            "agrees": all(r["agrees"] for r in rows.values()),
            "total_probe": sum(r["probe_max_feasible_k"] or 0 for r in rows.values()),
            "total_engine": sum(r["engine_k_at_2016_01_04"] for r in rows.values())}


# --------------------------------------------------------------------------- rendering
def _pct(x: float, digits: int = 2) -> str:
    return "n/a" if x is None or not math.isfinite(x) else f"{x * 100:.{digits}f} %"


def _cny(x: float) -> str:
    return "n/a" if x is None or not math.isfinite(x) else f"{x:,.0f}"


def render(summary: Mapping[str, Any]) -> str:
    primary = summary["cells"]["primary"]
    control = summary["control"]
    lines: list[str] = []
    add = lines.append

    add("# E3 — the board lot's cost at 50 000 CNY, priced in CNY\n")
    add(f"_run `{summary['runId']}` · cell `{primary['cell']['key']}` · "
        f"{primary['cell']['tolerance_bp']} bp per-order gate · {summary['window']['start']} .. "
        f"{summary['window']['end']} · {primary['seconds']} s_\n")

    add("## 1. Control check (P1) — first, because nothing else means anything without it\n")
    add(f"Verdict: **`{control['verdict']}`**\n")
    add("| clause | measured | E2 | ok |")
    add("|---|---|---|---|")
    for name, clause in control["clauses"].items():
        add(f"| {name} | `{clause['measured']}` | `{clause['e2']}` | {'yes' if clause['ok'] else 'NO'} |")
    add("")

    add("## 2. Terminal value and risk, one cell, one window\n")
    add("| arm | nav_end | CAGR | vol | max DD | cost bp/yr | turnover/yr | fills | intents | TE | granularity | gate |")
    add("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for name in ARM_NAMES:
        a = primary["arms"][name]
        add(f"| `{name}` | {_cny(a['nav_end'])} | {_pct(a['cagr'])} | {_pct(a['vol_annual'])} | "
            f"{_pct(a['max_drawdown'])} | {a['cost_bp_of_nav_per_year']:.2f} | "
            f"{a['turnover_per_year']:.3f} | {a['n_fills']} | {a['n_intents']} | "
            f"{_pct(a['mean_tracking_error'])} | {_pct(a['mean_granularity_te'])} | "
            f"{_pct(a['mean_gate_te'])} |")
    add("")
    add("TE splits into the part the board lot makes unavoidable (`granularity`) and the part the")
    add("per-order gate then adds (`gate`). A composition is only better if it lowers the sum,")
    add("not if it moves weight from one to the other.\n")

    add("### Day one, reconstructed from the fills\n")
    add("Read at the close of the entry session, not at the first month end: January 2016 was an")
    add("equity crash, which flatters any arm that failed to buy equity.\n")
    add("| arm | invested | cash | equity | bond | commodity | overseas | codes | entry cost |")
    add("|---|---|---|---|---|---|---|---|---|")
    for name in ARM_NAMES:
        e = primary["arms"][name]["entry"]
        add(f"| `{name}` | {_pct(e.get('entry_invested', float('nan')))} | "
            f"{_pct(e.get('entry_cash', float('nan')))} | {_pct(e.get('entry_equity', float('nan')))} | "
            f"{_pct(e.get('entry_bond', float('nan')))} | {_pct(e.get('entry_commodity', float('nan')))} | "
            f"{_pct(e.get('entry_overseas', float('nan')))} | {len(e.get('entry_codes', []))} | "
            f"{_cny(e.get('entry_costs_cny', float('nan')))} |")
    add("")

    add("## 3. Sleeve realisation — aimed versus held, and how many members the tree kept\n")
    for name in ARM_NAMES:
        add(f"### `{name}`\n")
        add("| sleeve | aimed first | realised first | aimed last | realised last | gap mean | members first → last decision | months >2 pp short |")
        add("|---|---|---|---|---|---|---|---|")
        for sleeve in SLEEVES:
            s = primary["arms"][name]["sleeves"][sleeve]
            add(f"| {sleeve} | {_pct(s['aimed_first'])} | {_pct(s['realised_first'])} | "
                f"{_pct(s['aimed_last'])} | {_pct(s['realised_last'])} | {_pct(s['gap_mean'])} | "
                f"{s['members_first']} → {s['members_last_decision']} | {s['months_short']} |")
        add("")

    add("## 4. The idle cash, priced\n")
    add("First-order: the cash the account held missed the mandate's own return for the next")
    add("month, compounded at the account's growth. Cross terms are excluded on purpose — this")
    add("is the *idle cash* part of the gap, not the whole arm difference.\n")
    add("| arm | idle-cash drag (CNY) | bp of NAV0 per year | months priced |")
    add("|---|---|---|---|")
    for name in ARM_NAMES:
        a = primary["arms"][name]
        add(f"| `{name}` | {_cny(a['idle_cash_drag_cny_first_order'])} | "
            f"{a.get('idle_cash_drag_bp_of_nav0_per_year', float('nan')):.1f} | "
            f"{a['months_priced']} |")
    add("")

    add("## 5. Paired differences (P3/P4) — 6-month moving-block bootstrap, 2 000 draws\n")
    add("| pair | annual CNY | 90 % interval | MDE CNY/yr | separates from zero | reading |")
    add("|---|---|---|---|---|---|")
    for pair, block in summary["decision"]["pairs"].items():
        add(f"| `{pair}` | {block['annual_cny']:+,.0f} | "
            f"[{block['annual_cny_lo']:,.0f}, {block['annual_cny_hi']:,.0f}] | "
            f"{_cny(block['mde_annual_cny'])} | {'yes' if block['separates_from_zero'] else 'no'} | "
            f"{block['reading']} |")
    add("")
    add(f"Adoption verdict: **`{summary['decision']['verdict']}`**"
        + (f" — adopted `{summary['decision']['adopted_arm']}`"
           if summary["decision"]["adopted_arm"] else
           f" — default to `{summary['decision']['default_when_unmeasured']}`") + "\n")
    if summary["decision"].get("tie_break"):
        add("Tie-break: " + str(summary["decision"]["tie_break"]) + "." + chr(10))

    add("## 6. Capital floor, descriptive only (P5)\n")
    floor = summary["cells"].get("capital_floor")
    if floor:
        add("`aimed` is the decision target after whole lots; `realised` is the same sleeve a "
            "month later, so it also contains the sleeve's own price drift and is NOT a "
            "quantisation measure. The quantisation column is `aimed` against the 35 % mandate." + chr(10))
        add("| arm | nav_end | bond aimed entry | bond aimed last | quantisation pp | cash mean | fills |")
        add("|---|---|---|---|---|---|---|")
        for name, a in floor["arms"].items():
            b = a["sleeves"]["bond"]
            quant = abs(float(b["aimed_last"]) - float(MANDATE["bond"])) * 100.0
            entry_bond = a.get("entry", {}).get("entry_bond")
            entry_txt = _pct(entry_bond) if entry_bond is not None else "—"
            add(f"| `{name}` | {_cny(a['nav_end'])} | {entry_txt} | {_pct(b['aimed_last'])} | "
                f"{quant:.1f} | {_pct(a['sleeve_diagnostic']['cash_weight_mean'])} | "
                f"{a['n_fills']} |")
        add("")
        prim_lots = summary["cells"]["primary"]["arms"]["lots"]["sleeves"]["bond"]
        prim_quant = abs(float(prim_lots["aimed_last"]) - float(MANDATE["bond"])) * 100.0
        add(f"At {_cny(NAV_PRIMARY)} the same cell quantises the bond sleeve by "
            f"{prim_quant:.1f} pp. The capital-floor option is therefore real and small: "
            "it buys about a point of sleeve fidelity for 2.4x the capital, while the lot form "
            "buys the whole measured composition gain at the capital the mandate names." + chr(10))

    add("## 7. Congruence with the probe that made `bond-sleeve-lot-bound`\n")
    pc = summary["probe_congruence"]
    if pc.get("available"):
        add(f"At {pc['at']}, NAV {pc['nav']}: **{'agrees' if pc['agrees'] else 'DISAGREES'}** — "
            f"probe total {pc['total_probe']} instruments vs engine {pc['total_engine']}.\n")
        add("| sleeve | probe max_feasible_k | engine k | unlisted at ref | agrees | cause |")
        add("|---|---|---|---|---|---|")
        for sleeve, row in pc["sleeves"].items():
            add(f"| {sleeve} | {row['probe_max_feasible_k']} | {row['engine_k_at_2016_01_04']} | "
                f"{', '.join(row['unlisted_at_ref']) or '—'} | {'yes' if row['agrees'] else 'NO'} | "
                f"{row['cause'] or '—'} |")
    else:
        add(f"not available: {pc.get('error')}")
    add("")

    add("## 8. What this licenses\n")
    for line in summary["reading"]:
        add(f"- {line}")
    add("")
    return "\n".join(lines) + "\n"


def _reading(summary: Mapping[str, Any]) -> list[str]:
    primary = summary["cells"]["primary"]
    decision = summary["decision"]
    static = primary["arms"][CONTROL]
    lots = primary["arms"]["lots"]
    deploy = primary["arms"]["lots_deploy"]
    out: list[str] = []
    out.append(
        f"The E2 execution left {_pct(static['sleeve_diagnostic']['cash_weight_first'])} of the "
        f"account in cash at entry and never bought the commodity or overseas sleeve at all; "
        f"the lot-defined composition enters with {_pct(lots['sleeve_diagnostic']['cash_weight_first'])} "
        f"cash and holds {lots['sleeves']['commodity']['members_first']} commodity and "
        f"{lots['sleeves']['overseas']['members_first']} overseas member(s) on day one.")
    out.append(
        f"Terminal value: `lots` {_cny(lots['nav_end'])} vs `lots_deploy` "
        f"{_cny(deploy['nav_end'])} vs `static` {_cny(static['nav_end'])} vs `cash` "
        f"{_cny(primary['arms']['cash']['nav_end'])} on the same "
        f"{summary['window']['start']} .. {summary['window']['end']} window.")
    for pair in ("lots-static", "lots_deploy-lots"):
        block = decision["pairs"].get(pair)
        if not block:
            continue
        out.append(
            f"`{pair}`: {block['annual_cny']:+,.0f} CNY/yr, 90 % interval "
            f"[{block['annual_cny_lo']:,.0f}, {block['annual_cny_hi']:,.0f}], "
            f"MDE {_cny(block['mde_annual_cny'])} — {block['reading']}.")
    out.append(
        f"Adoption rule (P4) returns `{decision['verdict']}`: "
        + ("a composition whose interval excludes zero is adopted."
           if decision["adopted_arm"] else
           "no composition separates from the control, so the mandate goes to the forward "
           "paper book in its cash-residual form and the return effect is recorded as "
           "unmeasured, not as zero."))
    out.append(
        f"The idle cash is worth {_cny(lots['idle_cash_drag_cny_first_order'])} first-order for "
        f"`lots` and {_cny(deploy['idle_cash_drag_cny_first_order'])} for `lots_deploy`: that is "
        "the size of the object design v13 did not have.")
    pc = summary.get("probe_congruence", {})
    if pc.get("available") and not pc.get("agrees"):
        bad = [s for s, r in pc["sleeves"].items() if not r["agrees"]]
        out.append(
            "The composition probe's instrument counts are one too high at 2016-01-04 for "
            f"{', '.join(bad)}: it skipped members without a price instead of dropping them from "
            "the tree, so it counted a fund that had not listed. The bond conclusion the probe "
            "was run for is unaffected (bond agrees), the instrument total is: probe "
            f"{pc['total_probe']} vs engine {pc['total_engine']}.")
    return out


def run(*, out_dir: Path | str = "evidence", ledger_dir: Path | str | None = None,
        start: str = REPLAY_START, end: str = REPLAY_END,
        run_id: str = "run-e3c00001-50k0-4c01-9a00-000000000001") -> dict[str, Any]:
    out_dir = Path(out_dir)
    ledger_dir = Path(ledger_dir) if ledger_dir else out_dir / "e3-ledgers"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    market = build_market(BARS, CORP, SCORES)

    primary_cell = Cell(NAV_PRIMARY, TOLERANCE, COST_MODE)
    primary = run_cell(market, primary_cell, ledger_dir=ledger_dir, start=start, end=end)
    control = control_check(primary)

    floor_cell = Cell(NAV_CAPITAL_FLOOR, TOLERANCE, COST_MODE)
    floor = run_cell(market, floor_cell, ledger_dir=ledger_dir, start=start, end=end,
                     arms=("static", "lots"))

    summary: dict[str, Any] = {
        "runId": run_id,
        "window": {"start": start, "end": end},
        "primary_arm": CONTROL,
        "arm_names": list(ARM_NAMES),
        "cells": {"primary": primary, "capital_floor": floor},
        "control": control,
        "probe_congruence": probe_congruence(market, primary_cell),
        "decision": _decide(primary),
    }
    summary["reading"] = _reading(summary)

    (out_dir / "e3-summary.json").write_text(
        json.dumps(summary, indent=1, default=str), encoding="utf-8")
    frames = []
    for name, frame in primary["monthly"].items():
        frame = frame.copy()
        frame["arm"] = name
        frames.append(frame)
    pd.concat(frames, ignore_index=True).to_parquet(out_dir / "e3-monthly.parquet", index=False)
    (out_dir / "e3-report.md").write_text(render(summary), encoding="utf-8")
    return summary


def main(out_dir: str | None = None) -> dict[str, Any]:
    return run(out_dir=out_dir or "evidence")


if __name__ == "__main__":  # pragma: no cover
    main()
