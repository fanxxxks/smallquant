"""L3 replay — one cost schedule, three trade-policy arms, net CNY out.

What this answers, in the terms the ledger reserved for it:

* **the trade-policy question** — does a rule that moves sleeve weights between annual
  rebalances earn more net CNY than rebalancing to the mandate once a year, at a 50 000 /
  75 000 / 100 000 CNY account and the measured cost floor?
* **F-113a8e8d-6** — does the post-rounding cost gate freeze marginal rebalancing?  Answered
  with two numbers per NAV: the share of intents suppressed, by reason, and the mean absolute
  gap between the realised and the intended sleeve weight (the gate's tracking error).
* **F-60b5f78a-7** — dividends and unit changes.  Both are `corp` records derived from the
  fund's own distribution record and from the price jump in the frozen bars
  (`data/corp_actions.parquet`), never assumed.

Design points that decide whether the number means anything:

1. **One cost model.** Commission 2.5 bp floored at 5 CNY per non-zero order, ETF stamp duty 0,
   transfer 0.01 bp, and slippage = half a 0.001 CNY tick per instrument, as a frozen RATE
   (`0.0005 / median_close` over the replay window) so that I-2 can re-price every fill on
   reload from the fee schedule alone.  The measured fill also crosses the tick: a buy pays
   `ceil_to_tick(open * (1 + slip))`, a sell `floor_to_tick(open * (1 - slip))`, so the
   slippage is paid in the price rather than double-charged in cash (`Cost.cash_cost` already
   excludes it).
2. **Decision at the close, fill at the next two opens.**  Sells at the open of the next
   session, buys at the open of the one after, so every buy is funded by settled cash (I-9)
   and the inter-phase gap is part of the measured path.
3. **The gate decides, not the engine.**  Every intent goes through `plan_order` on the final
   post-rounding notional at the same tolerance; a failing order is suppressed and counted,
   never resized (I-3).
4. Every fill, suppression, corporate action and month-end NAV is a ledger record, so a run is
   replayable byte for byte (I-6) and the artefacts are a projection of the ledger.

The score that feeds the parameterised arm is E1's ridge sleeve score (`evidence/
sleeve_scores.parquet`), the only arm E1 certified.  Ridge's `adopt_nonlinearity = false` is
why nothing here uses the MLP column.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from .ledger import Book, LedgerStore
from .order import Plan, execute_plan, plan_order
from .venue import ETF_STD, FeeSchedule, Instrument, Side, lot_notional, min_notional, q, round_to_lots

CENT = Decimal("0.01")
TICK = Decimal("0.001")

MANDATE: dict[str, float] = {"equity": 0.45, "bond": 0.35, "commodity": 0.10, "overseas": 0.10}
SLEEVE_MEMBERS: dict[str, tuple[str, ...]] = {
    "equity": ("510300", "510500", "512100"),
    "bond": ("511220", "511380"),
    "commodity": ("518880", "159934"),
    "overseas": ("513100", "513500", "159920"),
}
TRADED = tuple(c for members in SLEEVE_MEMBERS.values() for c in members)
W_EQ_FLOOR, W_EQ_CAP = 0.15, 0.75
TOLERANCE_BP = Decimal("15.1")
VOL_LOOKBACK = 60
ES_QUANTILE = 0.05
MIN_FIT_MONTHS = 24
RULE_FEATURES = ("z_score", "z_vol", "z_es", "z_dev")

REPLAY_START = "2016-01-04"
REPLAY_END = "2025-12-31"


# --------------------------------------------------------------------------- cost model
def slippage_table(market: "Market", codes: Sequence[str], mode: str = "measured") -> dict[str, float]:
    """One-way slippage RATE per code, frozen for the whole run.

    ``measured``  half a tick at the median close of the replay window — the 3.4-7.5 bp band
                  §5 measured, instrument by instrument;
    ``flat``      the inherited 0.0005 constant, kept only as a sensitivity row;
    ``worst``     half a tick at the CHEAPEST price the instrument ever traded in the window,
                  which is the same floor expressed at its most expensive.
    """
    out: dict[str, float] = {}
    for code in codes:
        series = market.close_of(code)
        window = series[(series.index >= REPLAY_START) & (series.index <= REPLAY_END)]
        if not len(window):
            window = series
        if mode == "flat":
            out[code] = 0.0005
        elif mode == "worst":
            out[code] = 0.0005 / float(window.min())
        elif mode == "measured":
            out[code] = 0.0005 / float(window.median())
        else:  # pragma: no cover - guard
            raise ValueError(f"unknown cost mode {mode}")
    return out


def fees_for(code: str, slippage: Mapping[str, float]) -> FeeSchedule:
    return FeeSchedule(
        commission_rate=Decimal("0.00025"),
        commission_min=Decimal("5.00"),
        stamp_rate=Decimal("0"),
        transfer_rate=Decimal("0.00001"),
        slippage_rate=Decimal(str(round(slippage[code], 12))),
        name="etf_std@measured" if slippage[code] != 0.0005 else "etf_std",
    )


def tick_round(price: Decimal, side: Side) -> Decimal:
    """Cross the tick: a buy pays up to the next 0.001 CNY, a sell down to the previous one."""
    ticks = price / TICK
    if side == "buy":
        return ticks.to_integral_value(rounding="ROUND_CEILING") * TICK
    return ticks.to_integral_value(rounding="ROUND_FLOOR") * TICK


# --------------------------------------------------------------------------- market frame
@dataclass
class Market:
    sessions: list[str]
    session_index: dict[str, int]
    close: dict[str, pd.Series]
    open: dict[str, pd.Series]
    dividends: dict[tuple[str, str], Decimal]
    splits: dict[tuple[str, str], Decimal]
    returns: dict[str, pd.Series]
    sleeve_returns: pd.DataFrame
    monthly: pd.DataFrame  # month-end decisions: one row per month with the features

    # -- accessors that survive suspensions ---------------------------------
    def close_of(self, code: str) -> pd.Series:
        return self.close[code]

    def mark(self, code: str, date: str) -> Decimal | None:
        series = self.close[code]
        upto = series[series.index <= date]
        return None if not len(upto) else Decimal(str(upto.iloc[-1]))

    def bar(self, code: str, date: str, field_: str = "open") -> Decimal | None:
        series = (self.open if field_ == "open" else self.close)[code]
        if date not in series.index:
            return None
        value = series.loc[date]
        return Decimal(str(value))

    def month_end_sessions(self) -> list[str]:
        out: list[str] = []
        for sess in self.sessions:
            out.append(sess)
        month_last: dict[str, str] = {}
        for sess in out:
            month_last[sess[:7]] = sess
        return [month_last[k] for k in sorted(month_last)]


def _dec(x: float) -> Decimal:
    return Decimal(str(round(float(x), 4)))


def build_market(
    bars_path: Path | str,
    corp_path: Path | str,
    scores_path: Path | str,
    *,
    start: str = REPLAY_START,
    end: str = REPLAY_END,
) -> Market:
    bars = pd.read_parquet(bars_path)
    bars = bars[bars["code"].isin(TRADED)].copy()
    bars["date"] = bars["date"].astype(str)
    corp = pd.read_parquet(corp_path)
    corp = corp[corp["code"].isin(TRADED)].copy()
    corp["date"] = corp["date"].astype(str)

    dividends: dict[tuple[str, str], Decimal] = {}
    splits: dict[tuple[str, str], Decimal] = {}
    for row in corp.itertuples(index=False):
        key = (str(row.code), str(row.date))
        if row.action == "dividend":
            if float(row.value) > 0:
                dividends[key] = _dec(row.value)
        elif row.action == "split":
            splits[key] = _dec(row.value)

    close: dict[str, pd.Series] = {}
    open_: dict[str, pd.Series] = {}
    returns: dict[str, pd.Series] = {}
    for code, group in bars.groupby("code", sort=True):
        g = group.sort_values("date")
        idx = pd.Index(g["date"].tolist())
        c = pd.Series(g["close"].astype(float).to_numpy(), index=idx)
        o = pd.Series(g["open"].astype(float).to_numpy(), index=idx)
        close[code] = c.round(4)
        open_[code] = o.round(4)
        # total return: undo the unit change, add the cash distribution
        prev = c.shift(1)
        scale = pd.Series(1.0, index=idx)
        add = pd.Series(0.0, index=idx)
        for (c_code, date), ratio in splits.items():
            if c_code == code and date in idx:
                scale.loc[date] = float(ratio)
        for (c_code, date), per_share in dividends.items():
            if c_code == code and date in idx:
                add.loc[date] = float(per_share)
        returns[code] = (c * scale + add) / prev - 1.0

    sessions = sorted({d for s in close.values() for d in s.index if start <= d <= end})
    session_index = {s: i for i, s in enumerate(sessions)}

    sleeve_returns = pd.DataFrame(index=pd.Index(sessions, name="date"))
    for sleeve, members in SLEEVE_MEMBERS.items():
        frame = pd.DataFrame({c: returns[c].reindex(sessions) for c in members})
        sleeve_returns[sleeve] = frame.mean(axis=1, skipna=True)

    market = Market(
        sessions=sessions,
        session_index=session_index,
        close=close,
        open=open_,
        dividends=dividends,
        splits=splits,
        returns=returns,
        sleeve_returns=sleeve_returns,
        monthly=pd.DataFrame(),
    )
    market.monthly = _monthly_features(market, scores_path)
    return market


def _monthly_features(market: Market, scores_path: Path | str) -> pd.DataFrame:
    """Month-end feature row per decision: the volatility state, the shortfall, the score."""
    eq = market.sleeve_returns["equity"]
    vol = eq.rolling(VOL_LOOKBACK, min_periods=VOL_LOOKBACK // 2).std() * math.sqrt(252)
    es = eq.rolling(VOL_LOOKBACK, min_periods=VOL_LOOKBACK // 2).apply(
        lambda x: float(np.mean(np.sort(x)[: max(1, int(math.ceil(len(x) * ES_QUANTILE)))])), raw=True
    )
    month_ends = market.month_end_sessions()
    rows = []
    for sess in month_ends:
        rows.append(
            {
                "date": sess,
                "sigma_hat": float(vol.get(sess, np.nan)),
                "es60": float(es.get(sess, np.nan)),
            }
        )
    frame = pd.DataFrame(rows)
    # expanding median of the volatility estimate: the target is the account's own history,
    # never a constant chosen after seeing the result
    frame["sigma_target"] = frame["sigma_hat"].expanding(min_periods=12).median()

    scores = pd.read_parquet(scores_path)
    scores = scores[scores["arm"] == "ridge"].copy()
    scores["date"] = pd.to_datetime(scores["trade_date"].astype(str)).dt.strftime("%Y-%m-%d")
    per_month = (
        scores.groupby(["date"])
        .agg(score=("score", "mean"), deviation=("deviation", "mean"), coverage=("coverage", "mean"))
        .reset_index()
    )
    # the score is stamped on the index's month-end; map it onto the decision session of the
    # same month, and carry the newest available value when a month is missing
    per_month["month"] = per_month["date"].str[:7]
    frame["month"] = frame["date"].str[:7]
    merged = frame.merge(per_month.drop(columns=["date"]), on="month", how="left").sort_values("month")
    merged[["score", "deviation", "coverage"]] = merged[["score", "deviation", "coverage"]].ffill()

    # next-month equity sleeve return: the label the parameterised arm is fitted on
    eq_me = eq.reindex(month_ends)
    growth = (1.0 + eq).cumprod()
    growth_me = growth.reindex(month_ends)
    merged["y_next"] = (growth_me.shift(-1) / growth_me - 1.0).to_numpy()

    for src, dst in (("score", "z_score"), ("sigma_hat", "z_vol"), ("es60", "z_es"), ("deviation", "z_dev")):
        series = merged[src].astype(float)
        mean = series.expanding(min_periods=12).mean()
        sd = series.expanding(min_periods=12).std()
        merged[dst] = (series - mean) / sd
    return merged.reset_index(drop=True)


# --------------------------------------------------------------------------- arms
@dataclass(frozen=True)
class Arm:
    name: str
    kind: str  # static | vol | rule | lots | cash | hold
    monthly_target: bool
    # A *composition rule* rather than a weight vector: the sleeve tree stops where the board
    # lot makes a slice unbuyable, and the sleeve target becomes its expressed weight.  See
    # `lot_composition`.  `redeploy` hands the unexpressed fraction to the sleeves that did
    # express their target instead of leaving it in cash.
    lot_defined: bool = False
    redeploy: bool = False


ARMS: dict[str, Arm] = {
    "static": Arm("static", "static", False),
    "vol": Arm("vol", "vol", True),
    "rule": Arm("rule", "rule", True),
    "lots": Arm("lots", "lots", False, lot_defined=True),
    "lots_deploy": Arm("lots_deploy", "lots", False, lot_defined=True, redeploy=True),
    "cash": Arm("cash", "cash", False),
    # ---- buy-once arms -----------------------------------------------------
    # `hold` is the arm §9 kill criterion 4 needed and the workspace never had: put the book on
    # at the entry session and never submit another target.  It differs from `static` in exactly
    # one way - `static` re-submits the mandate every January (`target_weights`, is_annual) - so
    # hold-vs-static isolates the annual re-submission, while the two lot variants keep the entry
    # composition of `lots` / `lots_deploy` and isolate it against those.
    "hold": Arm("hold", "hold", False),
    "hold_lot": Arm("hold_lot", "hold", False, lot_defined=True),
    "hold_deploy": Arm("hold_deploy", "hold", False, lot_defined=True, redeploy=True),
}


def available_members(market: "Market", sleeve: str, date: str) -> tuple[str, ...]:
    """Sleeve members with a bar at or before `date`.

    511380 lists on 2020-04-07 and 512100 on 2016-11-04, so the sleeve is equal-weighted over
    the members that exist: putting 17.5 % of the account into a fund that has not launched is
    not a missing trade, it is a wrong target.
    """
    out = []
    for code in SLEEVE_MEMBERS[sleeve]:
        series = market.close[code]
        if len(series) and series.index[0] <= date:
            out.append(code)
    return tuple(out)


def sleeve_weights(w_equity: float) -> dict[str, float]:
    """Move the equity weight and scale the other sleeves to keep their proportions."""
    rest = 1.0 - w_equity
    scale = rest / (1.0 - MANDATE["equity"])
    out = {"equity": w_equity}
    for sleeve in ("bond", "commodity", "overseas"):
        out[sleeve] = MANDATE[sleeve] * scale
    return out


def code_gate(code: str, tolerance_bp: Decimal | float, slippage: Mapping[str, float],
              side: str = "buy") -> Decimal:
    """The 15.1 bp gate for ONE code, with that code's own slippage inside the fee schedule."""
    return min_notional(tolerance_bp, side, fees_for(code, slippage)) or Decimal("0")


def sleeve_floor(market: "Market", codes: Sequence[str], date: str,
                 tolerance_bp: Decimal | float, slippage: Mapping[str, float]) -> Decimal:
    """Smallest slice that can be entered on ONE code: the larger of the gate and one lot.

    Two different constraints live here and only one of them was in design v13.  The cost
    gate says what one order must be worth before its commission can be amortised; the board
    lot says what one order *can* be.  For a par-quoted bond ETF the lot is 10 000-14 135 CNY,
    roughly three times the gate, so the lot is the binding number and no tolerance fixes it.
    """
    need = Decimal("0")
    for code in codes:
        price = market.mark(code, date)
        if price is None:
            continue
        need = max(need, max(code_gate(code, tolerance_bp, slippage), lot_notional(price, 100)))
    return need


def lot_composition(
    market: "Market",
    date: str,
    weights: Mapping[str, float],
    nav: Decimal,
    tolerance_bp: Decimal | float,
    slippage: Mapping[str, float],
    *,
    redeploy: bool = False,
) -> tuple[dict[str, float], dict[str, tuple[str, ...]]]:
    """Turn a declared sleeve vector into the vector the account can actually buy.

    One rule, applied per sleeve: keep the largest member count ``k`` for which the per-member
    slice still clears ``max(min_notional, one board lot)``, then express the sleeve at whole
    lots of the kept members (rounded DOWN - cash is binding, as in ``round_to_lots``).  The
    expressed weight is what the sleeve is worth once the lot has had its say, so a 35 % bond
    sleeve at 50 000 becomes a 20 % bond sleeve and says so instead of failing silently.

    ``redeploy`` (one pass, no iteration) gives the residual to the sleeves that are *not*
    lot-bound, pro rata to their declared weights: a sleeve is lot-bound when its own gap from
    target is at least half of the total gap.  Without ``redeploy`` the residual stays in cash,
    which is the honest reading of "the mandate cannot be held at this capital".
    """
    tol = Decimal(str(tolerance_bp))
    expressed: dict[str, Decimal] = {}
    members_out: dict[str, tuple[str, ...]] = {}
    for sleeve, weight in weights.items():
        available = available_members(market, sleeve, date)
        if not available or weight <= 0:
            expressed[sleeve] = Decimal("0")
            members_out[sleeve] = ()
            continue
        budget = Decimal(str(weight)) * nav
        k = len(available)
        while k > 1 and budget / k < sleeve_floor(market, available[:k], date, tol, slippage):
            k -= 1
        kept = available[:k]
        members_out[sleeve] = kept
        per = budget / k
        got = Decimal("0")
        for code in kept:
            price = market.mark(code, date)
            if price is None:
                continue
            got += lot_notional(price, 100) * round_to_lots(per, price, 100)
        expressed[sleeve] = got / nav if nav > 0 else Decimal("0")

    if not redeploy:
        return {s: float(expressed[s]) for s in weights}, members_out

    # Where the lot forces a shortfall, one sleeve normally owns nearly all of it: the shortfall
    # is a property of the instrument that quotes near par (one board lot = 20 %+ of its own
    # target), not of the rounding.  So a sleeve is "lot-bound" when its gap is at least half of
    # the total gap, and the residual is spread pro rata over the declared weights of the others.
    # A percentage tolerance was tried first and rejected: on 2016-01-04 two sleeves sat on
    # opposite sides of a 0.99 threshold by 0.0002, which turned a 10 % sleeve into 24 %.
    gaps = {s: Decimal(str(weights[s])) - expressed[s] for s in weights}
    total_gap = sum((g for g in gaps.values() if g > 0), Decimal("0"))
    if total_gap <= 0:
        return {s: float(expressed[s]) for s in weights}, members_out
    bound = {s for s, g in gaps.items() if g > 0 and g * 2 >= total_gap}
    free = [s for s in weights if s not in bound and weights[s] > 0]
    total_free = sum((Decimal(str(weights[s])) for s in free), Decimal("0"))
    # The bound sleeves keep exactly what the lot allowed; the free sleeves fill the rest, so
    # the target always sums to 1 and no intent is invented beyond the account's own NAV.
    free_target = Decimal("1") - sum((expressed[s] for s in bound), Decimal("0"))
    out: dict[str, float] = {}
    for sleeve, weight in weights.items():
        if sleeve in free and total_free > 0 and free_target > 0:
            out[sleeve] = float(free_target * Decimal(str(weight)) / total_free)
        else:
            out[sleeve] = float(expressed[sleeve])
    return out, members_out


def compose(
    arm: Arm,
    *,
    market: "Market",
    sess: str,
    row: Mapping[str, Any],
    theta: np.ndarray,
    is_annual: bool,
    prev: dict[str, float] | None,
    nav: Decimal,
    tolerance_bp: Decimal,
    slippage: Mapping[str, float],
) -> tuple[dict[str, float] | None, dict[str, tuple[str, ...]]]:
    """One decision: the sleeve vector to aim at, and which members each sleeve may hold.

    A weight arm returns the vector unchanged and every listed member; a lot-defined arm runs
    the vector through `lot_composition`, which is the only place the board lot is allowed to
    change a target.  Both cases return the member map so the whole replay - entry, rebalance,
    and the achievable-weight diagnostic - reads one composition instead of three.
    """
    weights = target_weights(arm, row=row, theta=theta, is_annual=is_annual, prev=prev)
    if weights is None:
        return None, {}
    if arm.lot_defined:
        return lot_composition(market, sess, weights, nav, tolerance_bp, slippage,
                               redeploy=arm.redeploy)
    return weights, {sleeve: available_members(market, sleeve, sess) for sleeve in weights}


def fit_rule_theta(monthly: pd.DataFrame, year: int) -> tuple[np.ndarray, int]:
    """OLS of next-month equity return on the four standardised features.

    Fitted on months whose decision date is strictly before the test year and whose label is
    observed; four coefficients, nothing else is fitted (I-7).  Below ``MIN_FIT_MONTHS`` the
    arm carries ``theta = 0``, which makes it the mandate at a monthly calendar — the honest
    statement is that the parameterised arm has no information yet, not that it has an edge.
    """
    cutoff = f"{year}-01-01"
    rows = monthly[(monthly["date"] < cutoff) & monthly[list(RULE_FEATURES)].notna().all(axis=1)
                   & monthly["y_next"].notna()]
    if len(rows) < MIN_FIT_MONTHS:
        return np.zeros(len(RULE_FEATURES)), len(rows)
    x = rows[list(RULE_FEATURES)].to_numpy(dtype="float64")
    y = rows["y_next"].to_numpy(dtype="float64")
    theta, *_ = np.linalg.lstsq(x, y, rcond=None)
    return theta, len(rows)


def _num(row: Mapping[str, Any], key: str) -> float:
    """Coerce a monthly-feature cell to float, `nan` when absent.

    The entry decision happens on a date that is not a month end, so its row is empty:
    every feature is missing there and the arms must fall back to the mandate instead of
    raising a TypeError out of `np.isfinite`.
    """
    value = row.get(key) if hasattr(row, "get") else None
    if value is None:
        return float("nan")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def target_weights(
    arm: Arm,
    *,
    row: Mapping[str, Any],
    theta: np.ndarray,
    is_annual: bool,
    prev: dict[str, float] | None,
) -> dict[str, float] | None:
    """Sleeve weights to hold after this decision; ``None`` = do not touch the book."""
    if arm.kind in ("static", "lots"):
        return dict(MANDATE) if (is_annual or prev is None) else None
    if arm.kind == "cash":
        return {sleeve: 0.0 for sleeve in MANDATE}
    if arm.kind == "vol":
        sigma_hat = _num(row, "sigma_hat")
        sigma_target = _num(row, "sigma_target")
        if not np.isfinite(sigma_hat) or not np.isfinite(sigma_target) or sigma_hat <= 0:
            return dict(MANDATE) if prev is None else None
        w_eq = float(np.clip(MANDATE["equity"] * sigma_target / sigma_hat, W_EQ_FLOOR, W_EQ_CAP))
        return sleeve_weights(w_eq)
    if arm.kind == "rule":
        z = np.array([_num(row, k) for k in RULE_FEATURES], dtype="float64")
        if not np.isfinite(z).all():
            return dict(MANDATE) if prev is None else None
        tilt = float(np.dot(theta, z))
        w_eq = float(np.clip(MANDATE["equity"] * (1.0 + tilt), W_EQ_FLOOR, W_EQ_CAP))
        return sleeve_weights(w_eq)
    if arm.kind == "hold":
        # `prev is None` is true only on the entry decision: the replay sets `prev_weights` from
        # the entry vector before the monthly loop starts, and only a non-None decision updates it
        # again.  So this returns the mandate once and ``None`` forever after, which is the whole
        # of what "buy once and hold" means in this engine - no band, no calendar, no re-target.
        return dict(MANDATE) if prev is None else None
    raise ValueError(arm.kind)  # pragma: no cover


# --------------------------------------------------------------------------- replay
@dataclass
class ReplayResult:
    arm: str
    nav0: Decimal
    monthly: pd.DataFrame
    daily: pd.DataFrame
    stats: dict[str, Any]
    ledger_path: str
    fills: pd.DataFrame
    suppressions: pd.DataFrame
    corp: pd.DataFrame
    theta_by_year: dict[int, list[float]]


def replay(
    market: Market,
    arm: Arm,
    *,
    nav0: Decimal,
    tolerance_bp: Decimal | float = TOLERANCE_BP,
    cost_mode: str = "measured",
    ledger_path: Path | str,
    start: str = REPLAY_START,
    end: str = REPLAY_END,
) -> ReplayResult:
    tol = Decimal(str(tolerance_bp))
    sessions = [s for s in market.sessions if start <= s <= end]
    if not sessions:
        raise RuntimeError("no sessions in the replay window")

    slippage = slippage_table(market, TRADED, mode=cost_mode)
    instruments = {}
    for code in TRADED:
        klass = next(sl for sl, members in SLEEVE_MEMBERS.items() if code in members)
        instruments[code] = Instrument(code=code, name=code, klass=klass, lot=100, fees=fees_for(code, slippage))

    ledger_path = Path(ledger_path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    if ledger_path.exists():
        ledger_path.unlink()
    store = LedgerStore(ledger_path)
    book = Book(ledger=store, instruments=instruments)
    book.open(nav0, note=f"replay {arm.name} nav={nav0} tol={tol}bp cost={cost_mode}")

    # ---- schedule --------------------------------------------------------
    month_ends = {s: True for s in market.month_end_sessions()}
    month_row = {str(r["date"]): r for r in market.monthly.to_dict("records")}
    years = sorted({int(s[:4]) for s in sessions})
    theta_by_year: dict[int, list[float]] = {}
    fit_rows: dict[int, int] = {}
    for year in years:
        theta, n = fit_rule_theta(market.monthly, year)
        theta_by_year[year] = [float(t) for t in theta]
        fit_rows[year] = int(n)

    annual_months = {f"{y}-01" for y in years}

    pending: dict[int, list[tuple[str, str, Decimal]]] = {}  # session idx -> [(code, side, notional)]
    prev_weights: dict[str, float] | None = None

    monthly_rows: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []
    corp_rows: list[dict[str, Any]] = []
    suppress_rows: list[dict[str, Any]] = []

    def marks_at(sess: str) -> dict[str, Decimal]:
        out: dict[str, Decimal] = {}
        for code, lots in book.positions.items():
            if lots == 0:
                continue
            price = market.mark(code, sess)
            if price is None:
                raise RuntimeError(f"no mark for {code} at {sess}")
            out[code] = price
        return out

    def holdings_value(sess: str) -> dict[str, Decimal]:
        out = {}
        for code in TRADED:
            lots = book.positions.get(code, 0)
            price = market.mark(code, sess)
            out[code] = q((price or Decimal("0")) * lots * instruments[code].lot)
        return out

    # ---- entry -----------------------------------------------------------
    entry_sess = sessions[0]
    entry_row = month_row.get(entry_sess, {})
    entry_weights, entry_members = compose(
        arm,
        market=market,
        sess=entry_sess,
        row=entry_row,
        theta=np.zeros(len(RULE_FEATURES)),
        is_annual=True,
        prev=None,
        nav=nav0,
        tolerance_bp=tol,
        slippage=slippage,
    )
    entry_weights = entry_weights or dict(MANDATE)
    prev_weights = entry_weights
    entry_intents: list[tuple[str, str, Decimal]] = []
    for sleeve, weight in entry_weights.items():
        members = entry_members.get(sleeve) or available_members(market, sleeve, entry_sess)
        if not members or weight <= 0:
            continue
        per = Decimal(str(weight / len(members))) * nav0
        for code in members:
            entry_intents.append((code, "buy", q(per)))

    pending[0] = sorted(entry_intents, key=lambda x: (-x[2], x[0]))
    unlisted: list[dict[str, Any]] = []

    for i, sess in enumerate(sessions):
        book.settle(i)

        # corporate actions dated today, before any fill: cash from a distribution is
        # available to the rebalance that follows it in the same session
        for code in TRADED:
            key = (code, sess)
            if key in market.dividends:
                lots = book.positions.get(code, 0)
                per_share = market.dividends[key]
                rec = book.corporate_action(code=code, action="dividend", session=i, per_share=per_share)
                corp_rows.append(
                    {
                        "date": sess,
                        "code": code,
                        "action": "dividend",
                        "value": float(per_share),
                        "lots": lots,
                        "cash": float(q(per_share * lots * instruments[code].lot)),
                    }
                )
                del rec
            if key in market.splits:
                ratio = market.splits[key]
                lots = book.positions.get(code, 0)
                new_lots = int(Decimal(lots) * ratio)
                prev_price = market.mark(code, _prev_session(market, sess))
                price_after = (prev_price / ratio) if prev_price is not None else Decimal("0")
                residual = q((Decimal(lots) * ratio - new_lots) * instruments[code].lot * price_after)
                book.corporate_action(
                    code=code, action="split", session=i, ratio=ratio, residual_cash=residual
                )
                corp_rows.append(
                    {
                        "date": sess,
                        "code": code,
                        "action": "split",
                        "value": float(ratio),
                        "lots": lots,
                        "cash": float(residual),
                    }
                )

        # fills scheduled for this session
        for code, side, target in pending.pop(i, []):
            price = market.bar(code, sess, "open")
            if price is None:
                unlisted.append({"date": sess, "code": code, "side": side, "reason": "no_bar"})
                continue
            slip = Decimal(str(slippage[code]))
            slipped = price * (Decimal(1) + slip) if side == "buy" else price * (Decimal(1) - slip)
            exec_price = tick_round(Decimal(str(slipped)), side)
            plan = plan_order(
                instruments[code],
                side=side,
                target_notional=Decimal(target),
                price=exec_price,
                tolerance_bp=tol,
                available_cash=book.available_cash(i) if side == "buy" else None,
                sellable_lots=book.sellable_lots(code, i) if side == "sell" else None,
                session=i,
            )
            execute_plan(book, plan, session=i)
            if not plan.ok:
                suppress_rows.append(
                    {
                        "date": sess,
                        "code": code,
                        "side": side,
                        "reason": plan.reason,
                        "lots": plan.lots,
                        "notional": float(plan.notional),
                        "bp": float(plan.bp),
                        "tolerance_bp": float(tol),
                        "detail": plan.detail,
                    }
                )

        # decision at the close of a month end
        if month_ends.get(sess):
            row = month_row.get(sess) or month_row.get(max(k for k in month_row if k <= sess))
            theta = np.array(theta_by_year.get(int(sess[:4]), [0.0] * len(RULE_FEATURES)))
            nav = book.nav(marks_at(sess))
            weights, members_map = compose(
                arm,
                market=market,
                sess=sess,
                row=row,
                theta=theta,
                is_annual=sess[:7] in annual_months,
                prev=prev_weights,
                nav=nav,
                tolerance_bp=tol,
                slippage=slippage,
            )
            aimed = weights or prev_weights or dict(MANDATE)
            held = holdings_value(sess)
            realised_vals = {
                sleeve: float(sum(held.get(c, Decimal("0")) for c in SLEEVE_MEMBERS[sleeve]))
                for sleeve in SLEEVE_MEMBERS
            }
            realised = {k: v / float(nav) for k, v in realised_vals.items()}
            # What could the book hold if the target were rounded to board lots right now?
            # Without this the tracking error mixes two different failures: lots too coarse and
            # a gate that will not pay for the correction.
            achievable: dict[str, float] = {}
            for sleeve, weight in aimed.items():
                members = members_map.get(sleeve) or available_members(market, sleeve, sess)
                want = Decimal(str(weight)) * nav / max(1, len(members))
                got = Decimal("0")
                for code in members:
                    px = market.mark(code, sess)
                    if px is None:
                        continue
                    got += px * round_to_lots(want, px, 100) * 100
                achievable[sleeve] = float(got) / float(nav)
            z_values = np.array([row.get(k, np.nan) for k in RULE_FEATURES], dtype="float64")
            monthly_rows.append(
                {
                    "date": sess,
                    "nav": float(nav),
                    "cash": float(book.cash),
                    "w_equity_target": aimed["equity"],
                    "sigma_hat": float(row.get("sigma_hat", np.nan)),
                    "sigma_target": float(row.get("sigma_target", np.nan)),
                    "score": float(row.get("score", np.nan)),
                    "theta_dot_z": float(np.dot(theta, z_values)) if np.isfinite(z_values).all() else np.nan,
                    "realised_equity": realised["equity"],
                    "tracking_error": float(sum(abs(realised[k] - aimed[k]) for k in SLEEVE_MEMBERS)),
                    "granularity_te": float(sum(abs(achievable[k] - aimed[k]) for k in SLEEVE_MEMBERS)),
                    "gate_te": float(sum(abs(realised[k] - achievable[k]) for k in SLEEVE_MEMBERS)),
                    # per-sleeve, so a composition question can be answered without re-deriving
                    # holdings from the fill stream: aimed is what the arm asked for, realised
                    # is what the account held after the last fill.
                    **{f"aimed_{k}": float(aimed[k]) for k in SLEEVE_MEMBERS},
                    **{f"realised_{k}": float(realised[k]) for k in SLEEVE_MEMBERS},
                    **{f"members_{k}": len(members_map.get(k) or ()) for k in SLEEVE_MEMBERS},
                }
            )
            store.append(
                "mark",
                {"session": i, "note": f"month-end {sess}", "nav": str(nav),
                 "marks": {c: str(p) for c, p in marks_at(sess).items()}},
            )
            if weights is not None and i + 1 < len(sessions):
                prev_weights = weights
                sells: list[tuple[str, str, Decimal]] = []
                buys: list[tuple[str, str, Decimal]] = []
                for sleeve, weight in weights.items():
                    members = members_map.get(sleeve) or available_members(market, sleeve, sess)
                    if not members or weight <= 0:
                        continue
                    per = Decimal(str(weight / len(members))) * nav
                    for code in members:
                        current = held.get(code, Decimal("0"))
                        delta = q(per - current)
                        if delta < 0:
                            sells.append((code, "sell", q(-delta)))
                        elif delta > 0:
                            buys.append((code, "buy", delta))
                if sells:
                    pending[i + 1] = sorted(sells, key=lambda x: (-x[2], x[0]))
                if buys:
                    slot = i + 2 if i + 2 < len(sessions) else i + 1
                    pending[slot] = sorted(buys, key=lambda x: (-x[2], x[0]))

        marks = marks_at(sess)
        daily_rows.append({"date": sess, "nav": float(book.nav(marks)), "cash": float(book.cash)})

    # ---- projections -----------------------------------------------------
    records = list(store.records)
    fills = pd.DataFrame(
        [
            {
                "date": sessions[int(r.payload["session"])] if int(r.payload["session"]) < len(sessions) else "",
                "code": r.payload["code"],
                "side": r.payload["side"],
                "lots": int(r.payload["lots"]),
                "price": float(r.payload["price"]),
                "notional": float(r.payload["notional"]),
                "commission": float(r.payload["commission"]),
                "transfer": float(r.payload["transfer"]),
                "stamp": float(r.payload["stamp"]),
                "slippage": float(r.payload["slippage"]),
                "total_cost": float(r.payload["total_cost"]),
                "cost_bp": float(r.payload["cost_bp"]),
            }
            for r in records
            if r.kind == "fill"
        ]
    )
    suppressions = pd.DataFrame(suppress_rows)
    corp = pd.DataFrame(corp_rows)
    monthly = pd.DataFrame(monthly_rows)
    daily = pd.DataFrame(daily_rows)

    stats = summarise(
        arm=arm,
        nav0=nav0,
        monthly=monthly,
        daily=daily,
        fills=fills,
        suppressions=suppressions,
        corp=corp,
        tolerance_bp=tol,
        cost_mode=cost_mode,
        slippage=slippage,
        fit_rows=fit_rows,
        no_bar=len(unlisted),
    )
    return ReplayResult(
        arm=arm.name,
        nav0=nav0,
        monthly=monthly,
        daily=daily,
        stats=stats,
        ledger_path=str(ledger_path),
        fills=fills,
        suppressions=suppressions,
        corp=corp,
        theta_by_year=theta_by_year,
    )


def _prev_session(market: Market, sess: str) -> str:
    i = market.session_index.get(sess)
    if i is None or i == 0:
        return sess
    return market.sessions[i - 1]


# --------------------------------------------------------------------------- statistics
def summarise(
    *,
    arm: Arm,
    nav0: Decimal,
    monthly: pd.DataFrame,
    daily: pd.DataFrame,
    fills: pd.DataFrame,
    suppressions: pd.DataFrame,
    corp: pd.DataFrame,
    tolerance_bp: Decimal,
    cost_mode: str,
    slippage: Mapping[str, float],
    fit_rows: Mapping[int, int],
    no_bar: int = 0,
) -> dict[str, Any]:
    nav = monthly["nav"].to_numpy(dtype="float64")
    rets = np.concatenate([[nav[0] / float(nav0) - 1.0], nav[1:] / nav[:-1] - 1.0]) if len(nav) > 1 else np.array([])
    months = len(rets)
    years = months / 12.0
    end = float(nav[-1]) if len(nav) else float(nav0)
    cagr = (end / float(nav0)) ** (1 / years) - 1 if years > 0 and end > 0 else float("nan")
    vol = float(np.std(rets, ddof=1) * math.sqrt(12)) if months > 1 else float("nan")
    wealth = np.concatenate([[float(nav0)], nav])
    peak = np.maximum.accumulate(wealth)
    drawdown = float((wealth / peak - 1.0).min()) if len(wealth) else float("nan")

    total_cost = float(fills["total_cost"].sum()) if len(fills) else 0.0
    cash_cost = float((fills["commission"].sum() + fills["transfer"].sum() + fills["stamp"].sum())) if len(fills) else 0.0
    traded = float(fills["notional"].sum()) if len(fills) else 0.0
    n_fills = int(len(fills))
    n_intents = int(len(fills) + len(suppressions))
    by_reason = suppressions["reason"].value_counts().to_dict() if len(suppressions) else {}
    div_cash = float(corp.loc[corp["action"] == "dividend", "cash"].sum()) if len(corp) else 0.0
    split_cash = float(corp.loc[corp["action"] == "split", "cash"].sum()) if len(corp) else 0.0

    te = monthly["tracking_error"].to_numpy(dtype="float64") if "tracking_error" in monthly else np.array([])
    w_eq = monthly["w_equity_target"].to_numpy(dtype="float64") if "w_equity_target" in monthly else np.array([])

    return {
        "arm": arm.name,
        "nav0": float(nav0),
        "nav_end": end,
        "months": int(months),
        "years": years,
        "cagr": float(cagr),
        "vol_annual": vol,
        "max_drawdown": drawdown,
        "total_return": end / float(nav0) - 1.0,
        "cost_cny": total_cost,
        "cost_cash_cny": cash_cost,
        "cost_bp_of_nav_per_year": total_cost / float(nav0) / years * 1e4 if years > 0 else float("nan"),
        "traded_notional": traded,
        "turnover_per_year": traded / float(nav0) / years if years > 0 else float("nan"),
        "n_fills": n_fills,
        "n_intents": n_intents,
        "suppressed": int(len(suppressions)),
        "suppressed_share": float(len(suppressions) / n_intents) if n_intents else 0.0,
        "suppressed_by_reason": {k: int(v) for k, v in by_reason.items()},
        "no_bar_intents": int(no_bar),
        "dividend_cash": div_cash,
        "split_residual_cash": split_cash,
        "mean_tracking_error": float(np.nanmean(te)) if len(te) else float("nan"),
        "mean_granularity_te": float(np.nanmean(monthly["granularity_te"])) if "granularity_te" in monthly else float("nan"),
        "mean_gate_te": float(np.nanmean(monthly["gate_te"])) if "gate_te" in monthly else float("nan"),
        "max_tracking_error": float(np.nanmax(te)) if len(te) else float("nan"),
        "mean_target_equity": float(np.nanmean(w_eq)) if len(w_eq) else float("nan"),
        "min_target_equity": float(np.nanmin(w_eq)) if len(w_eq) else float("nan"),
        "max_target_equity": float(np.nanmax(w_eq)) if len(w_eq) else float("nan"),
        "equity_below_mandate": float(np.mean(w_eq < MANDATE["equity"] - 1e-9)) if len(w_eq) else float("nan"),
        "tolerance_bp": float(tolerance_bp),
        "cost_mode": cost_mode,
        "slippage_bp": {c: round(float(s) * 1e4, 4) for c, s in slippage.items()},
        "rule_fit_months": {int(k): int(v) for k, v in fit_rows.items()},
        "daily_sessions": int(len(daily)),
    }


def replay_fingerprint(result: ReplayResult) -> str:
    """I-6 evidence: the chain head of the run's own ledger."""
    store = LedgerStore(Path(result.ledger_path))
    return store.head
