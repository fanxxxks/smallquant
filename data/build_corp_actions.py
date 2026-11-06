#!/usr/bin/env python
"""Freeze the corporate-action table (cash distributions + unit changes) for the replay.

Two facts must be measured before any replay on raw prices, because a raw close drops on an
ex-date and jumps on a unit change (份额折算/合并) and both would otherwise land in the NAV as
a fake return:

  1. dividends  — from the fund's own cumulative-distribution record (Sina 分红送配), diffed per
                  event:  D_t = cum_t - cum_{t-1}  (CNY per ETF share, exactly the number
                  `Book.corporate_action(action="dividend", per_share=D_t)` credits to cash).
  2. unit changes — detected from the frozen raw bars as a single-session move no ETF in this
                  venue can produce (|r| > 40%), and the multiplier is then *solved* from the
                  forward-adjusted series, which is continuous across the event:
                        S = (raw_{t-1} / raw_t) * (qfq_t / qfq_{t-1})
                  so that `raw_t = raw_{t-1} * (1+r_market) / S`, with r_market the ordinary
                  market move carried by qfq.  S is then snapped to a clean multiplier when it
                  is within 1 %, and the snapped value is what the replay applies
                  (`Book.corporate_action(action="split", ratio=S)` multiplies lots).

Why not derive dividends from qfq as well: for 510300 the qfq/raw ratio drifts inside a
dividend-free window (checked below and written into the manifest), so qfq is a nonlinear
rescale there and inverting it for per-share cash would book a fake drift as dividends.

Output: data/corp_actions.parquet  (code, date, action, value, source, detail…)
        data/corp_actions.manifest.json
Run:    python D:/newquant/data/build_corp_actions.py
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import akshare as ak
import pandas as pd

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

ROOT = Path("D:/newquant")
BARS = ROOT / "data" / "etf_bars.parquet"
QFQ = ROOT / "data" / "etf_bars_qfq.parquet"
OUT = ROOT / "data" / "corp_actions.parquet"
MANIFEST = ROOT / "data" / "corp_actions.manifest.json"

RETRIES = 3
RETRY_SLEEP = 2.0
SPLIT_JUMP = 0.40          # |single-session move| above this is a unit change, not a return
SNAP_TOL = 0.01            # multiplier within 1 % of a clean value is snapped to it
NAV_TOL = 0.03             # snapped multiplier must explain the price jump to within 3 %

# Sina wants a market prefix. 51xxxx/58xxxx are Shanghai, 15xxxx/16xxxx are Shenzhen.
def sina_symbol(code: str) -> str:
    return ("sh" if code.startswith(("5", "6")) else "sz") + code


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.replace(",", "", regex=False), errors="coerce")


def fetch_dividends(code: str) -> tuple[pd.DataFrame, str | None]:
    """Cumulative-distribution record -> per-event cash distribution (CNY per share)."""
    last: str | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            raw = ak.fund_etf_dividend_sina(symbol=sina_symbol(code))
            break
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
            print(f"    [retry {attempt}/{RETRIES}] sina dividend {code}: {last}", file=sys.stderr)
            time.sleep(RETRY_SLEEP)
    else:
        return pd.DataFrame(columns=["date", "cum", "per_share"]), last or "unreachable"

    if raw is None or len(raw) == 0:
        return pd.DataFrame(columns=["date", "cum", "per_share"]), None

    # Column names arrive as Chinese labels; bind by position so an encoding change cannot
    # silently produce an empty frame.  (date, cumulative dividend per share)
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(raw.iloc[:, 0].astype(str), errors="coerce").dt.strftime("%Y-%m-%d"),
            "cum": _num(raw.iloc[:, 1]),
        }
    )
    frame = frame.dropna(subset=["date", "cum"]).sort_values("date").reset_index(drop=True)
    frame["per_share"] = frame["cum"].diff()
    first = frame["cum"].iloc[0] if len(frame) else None
    if first is not None and first > 0:
        frame.loc[0, "per_share"] = first  # the first cumulative figure is the first distribution
    return frame.dropna(subset=["per_share"]).reset_index(drop=True), None


def snap(value: float) -> tuple[float, bool]:
    """Snap a solved multiplier to a clean one when it is within SNAP_TOL of it."""
    for clean in (1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 10.0, 20.0, 100.0):
        if abs(value - clean) / clean <= SNAP_TOL:
            return clean, True
    for clean in (1 / 1.5, 1 / 2.0, 1 / 2.5, 1 / 3.0, 1 / 4.0, 1 / 5.0):
        if abs(value - clean) / clean <= SNAP_TOL:
            return round(clean, 6), True
    return round(value, 6), False


def detect_splits(bars: pd.DataFrame, qfq: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    merged = bars.merge(qfq, on=["code", "date"], how="left", suffixes=("", "_qfq"))
    merged = merged.sort_values(["code", "date"]).reset_index(drop=True)
    grouped = merged.groupby("code", sort=True)
    merged["raw_prev"] = grouped["close"].shift(1)
    merged["q_prev"] = grouped["qclose"].shift(1)
    merged["ret_raw"] = merged["close"] / merged["raw_prev"] - 1

    events = merged[merged["ret_raw"].abs() > SPLIT_JUMP].copy()
    rows: list[dict] = []
    notes: list[dict] = []
    for _, ev in events.iterrows():
        code = str(ev["code"])
        raw_prev, raw_close = float(ev["raw_prev"]), float(ev["close"])
        q_prev, q_close = float(ev["q_prev"]), float(ev["qclose"])
        solved = (raw_prev / raw_close) * (q_close / q_prev) if q_prev and q_close else float("nan")
        snapped, clean = snap(solved) if solved == solved else (float("nan"), False)
        # does the snapped multiplier explain the price jump, leaving only an ordinary move?
        implied_market = (raw_prev / snapped) / raw_close - 1 if snapped == snapped else float("nan")
        ok = bool(implied_market == implied_market and abs(implied_market) <= NAV_TOL)
        rows.append(
            {
                "code": code,
                "date": str(ev["date"]),
                "action": "split",
                "value": snapped,
                "source": "derived:raw_bars_x_qfq_continuity",
                "detail": json.dumps(
                    {
                        "raw_prev": raw_prev,
                        "raw_close": raw_close,
                        "ret_raw": round(float(ev["ret_raw"]), 6),
                        "solved": round(solved, 6) if solved == solved else None,
                        "snapped_clean": clean,
                        "implied_market_move": round(implied_market, 6) if implied_market == implied_market else None,
                        "nav_preserved": ok,
                    }
                ),
            }
        )
        if not ok:
            notes.append({"code": code, "date": str(ev["date"]), "reason": "multiplier does not explain the jump",
                          "implied_market_move": implied_market})
    return pd.DataFrame(rows), notes


def qfq_drift_check(merged: pd.DataFrame, dividends: pd.DataFrame) -> dict[str, Any]:
    """Is qfq/raw a clean scale?  Measured inside a dividend-free window per code."""
    out: dict[str, Any] = {}
    for code, group in merged.groupby("code", sort=True):
        g = group.sort_values("date").reset_index(drop=True)
        if g["qclose"].isna().any():
            out[code] = {"usable": False, "why": "no qfq rows"}
            continue
        div_dates = sorted(dividends.loc[dividends["code"] == code, "date"].astype(str))
        # longest run of sessions with no ex-date strictly inside it
        best_lo = best_hi = 0
        lo = 0
        div_idx = [i for i, d in enumerate(g["date"].astype(str)) if d in set(div_dates)]
        bounds = [-1] + div_idx + [len(g)]
        for a, b in zip(bounds[:-1], bounds[1:]):
            if b - a - 1 > best_hi - best_lo:
                best_lo, best_hi = a + 1, b - 1
        if best_hi - best_lo <= 5:
            out[code] = {"usable": True, "why": "too few ex-dates to test", "window": None}
            continue
        win = g.iloc[best_lo : best_hi + 1]
        ratio = (win["qclose"] / win["close"]).to_numpy()
        drift = float(ratio.max() / ratio.min() - 1) if ratio.min() > 0 else float("inf")
        out[code] = {
            "window": [str(win["date"].iloc[0]), str(win["date"].iloc[-1])],
            "sessions": int(len(win)),
            "div_free_drift_pct": round(drift * 100, 4),
            "usable": bool(drift < 0.002),
        }
    return out


def main() -> int:
    bars = pd.read_parquet(BARS)[["code", "date", "close"]]
    qfq = pd.read_parquet(QFQ)[["code", "date", "close"]].rename(columns={"close": "qclose"})
    codes = sorted(bars["code"].unique())

    div_frames: list[dict] = []
    div_status: dict[str, Any] = {}
    for code in codes:
        frame, err = fetch_dividends(code)
        n = 0 if frame is None else len(frame)
        div_status[code] = {"events": int(n), "error": err}
        if n:
            for _, r in frame.iterrows():
                div_frames.append(
                    {
                        "code": code,
                        "date": str(r["date"]),
                        "action": "dividend",
                        "value": round(float(r["per_share"]), 6),
                        "source": "sina:fund_etf_dividend_sina",
                        "detail": json.dumps({"cum_after": round(float(r["cum"]), 6)}),
                    }
                )
        print(f"  {code}: {n} distribution events{' ERR ' + str(err) if err else ''}", file=sys.stderr)

    dividends_long = pd.DataFrame(div_frames)
    splits, split_notes = detect_splits(bars, qfq)

    merged = bars.merge(qfq, on=["code", "date"], how="left")
    drift = qfq_drift_check(merged, dividends_long)

    actions = pd.concat([dividends_long, splits], ignore_index=True)
    if len(actions):
        actions = actions.sort_values(["code", "date", "action"]).reset_index(drop=True)
        actions = actions[["code", "date", "action", "value", "source", "detail"]]
    actions.to_parquet(OUT, index=False)

    checks: dict[str, Any] = {
        "all_codes_covered": sorted(actions["code"].unique()) == codes if len(actions) else False,
        "positive_dividends": bool((actions.loc[actions["action"] == "dividend", "value"] > 0).all())
        if (actions["action"] == "dividend").any()
        else True,
        "split_count": int((actions["action"] == "split").sum()),
        "splits_with_unexplained_jump": split_notes,
        "dividend_events": int((actions["action"] == "dividend").sum()),
        "dividend_fetch_errors": {c: v["error"] for c, v in div_status.items() if v["error"]},
        "qfq_usable_as_scale": {c: v["usable"] for c, v in drift.items()},
    }
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {"bars": str(BARS), "bars_sha256": sha256(BARS), "qfq": str(QFQ), "qfq_sha256": sha256(QFQ),
                    "akshare_version": ak.__version__},
        "parameters": {"split_jump": SPLIT_JUMP, "snap_tolerance": SNAP_TOL, "nav_tolerance": NAV_TOL},
        "row_count": int(len(actions)),
        "output_sha256": sha256(OUT),
        "checks": checks,
        "per_code_status": div_status,
        "qfq_drift": drift,
    }
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nwrote {OUT} rows={len(actions)}")
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    if len(splits):
        print("\nsplits:")
        print(splits[["code", "date", "value", "detail"]].to_string(index=False))
    in_window = actions[(actions["date"] >= "2016-01-01") & (actions["action"] == "dividend")].copy()
    if len(in_window):
        print("\ndividends in replay window, per code / per year:")
        in_window["year"] = in_window["date"].str[:4]
        print(in_window.groupby(["code", "year"])["value"].agg(["count", "sum"]).round(4).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
