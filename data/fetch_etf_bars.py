#!/usr/bin/env python
"""Frozen ETF daily-bar artefact builder for D:/newquant.

Pulls daily OHLCV history for a fixed candidate sleeve universe from akshare,
normalises it to an English schema, and writes:
  D:/newquant/data/etf_bars.parquet          (pyarrow, snappy)
  D:/newquant/data/etf_bars.manifest.json    (coverage / provenance)

Source order per code:
  1. akshare.fund_etf_hist_em(symbol=code, period="daily", adjust="")
  2. akshare.fund_etf_hist_sina(symbol=<sh|sz>+code)
Intraday endpoints are never used. No rows are ever fabricated.

Run: D:/minequant/.venv/Scripts/python.exe D:/newquant/data/fetch_etf_bars.py
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import akshare as ak
import pandas as pd

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

OUT_DIR = Path("D:/newquant/data")
PARQUET_PATH = OUT_DIR / "etf_bars.parquet"
MANIFEST_PATH = OUT_DIR / "etf_bars.manifest.json"

START_DATE = "20130101"
END_DATE = "20261104"
RETRIES = 3
RETRY_SLEEP = 2.0
SHORT_HISTORY_ROWS = 250

UNIVERSE: list[tuple[str, str]] = [
    ("equity", "510300"),
    ("equity", "510500"),
    ("equity", "159915"),
    ("equity", "512100"),
    ("bond", "511010"),
    ("bond", "511260"),
    ("bond", "511220"),
    ("bond", "511380"),
    ("commodity", "518880"),
    ("commodity", "159934"),
    ("overseas", "513100"),
    ("overseas", "513500"),
    ("overseas", "159920"),
    ("cash-like", "511990"),
    ("cash-like", "511880"),
]

EM_RENAME = {
    "日期": "date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "振幅": "amplitude",
    "涨跌幅": "pct_chg",
    "涨跌额": "chg",
    "换手率": "turnover",
}

NUMERIC_COLS = [
    "open",
    "close",
    "high",
    "low",
    "volume",
    "amount",
    "amplitude",
    "pct_chg",
    "chg",
    "turnover",
]

BAR_COLS = ["date"] + NUMERIC_COLS
FINAL_COLS = ["code"] + BAR_COLS

# eastmoney reports volume in 手 (lots, 100 shares); sina reports raw share counts.
VOLUME_UNIT = {"eastmoney": "lots", "sina": "shares"}


def sina_symbol(code: str) -> str:
    """5xxxxx -> sh, 1xxxxx -> sz (Shanghai / Shenzhen ETF prefixes)."""
    if code.startswith("5"):
        return f"sh{code}"
    if code.startswith("1"):
        return f"sz{code}"
    raise ValueError(f"unmapped exchange prefix for code {code}")


def with_retries(fn, label: str):
    """Call fn() up to RETRIES times with a fixed sleep. Return (result, error_text)."""
    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            return fn(), None
        except Exception as exc:  # noqa: BLE001 - record, never swallow silently
            last_err = f"{type(exc).__name__}: {exc}"
            print(f"    [retry {attempt}/{RETRIES}] {label}: {last_err}", file=sys.stderr)
            if attempt < RETRIES:
                time.sleep(RETRY_SLEEP)
    return None, last_err


def normalise(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Map a raw akshare frame onto the frozen English schema."""
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=BAR_COLS)

    out = df.copy()
    if source == "eastmoney":
        out = out.rename(columns=EM_RENAME)
    else:  # sina returns english headers already, but be lenient
        out = out.rename(columns=EM_RENAME)
        out.columns = [str(c).strip().lower() for c in out.columns]
        alias = {
            "trade_date": "date",
            "vol": "volume",
            "volume": "volume",
            "amount": "amount",
            "pricechange": "chg",
            "changepercent": "pct_chg",
            "turnoverratio": "turnover",
        }
        out = out.rename(columns={k: v for k, v in alias.items() if k in out.columns})

    if "date" not in out.columns:
        raise RuntimeError(f"no date column after normalisation: {list(out.columns)}")

    # date -> canonical YYYY-MM-DD string
    d = out["date"]
    if pd.api.types.is_datetime64_any_dtype(d):
        out["date"] = d.dt.strftime("%Y-%m-%d")
    else:
        out["date"] = pd.to_datetime(d.astype(str), errors="coerce").dt.strftime("%Y-%m-%d")

    for col in NUMERIC_COLS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").astype("float64")
        else:
            out[col] = pd.Series([float("nan")] * len(out), dtype="float64")

    out = out.dropna(subset=["date"])
    return out[BAR_COLS].reset_index(drop=True)


def fetch_code(code: str) -> tuple[pd.DataFrame, str, str | None]:
    """Return (frame, source, error_message). source is '' when nothing produced rows."""
    errors: list[str] = []

    df, err = with_retries(
        lambda: ak.fund_etf_hist_em(
            symbol=code,
            period="daily",
            start_date=START_DATE,
            end_date=END_DATE,
            adjust="",
        ),
        f"fund_etf_hist_em({code})",
    )
    if err:
        errors.append(f"eastmoney: {err}")
    if df is not None and len(df) > 0:
        return normalise(df, "eastmoney"), "eastmoney", None

    sym = sina_symbol(code)
    df, err = with_retries(lambda: ak.fund_etf_hist_sina(symbol=sym), f"fund_etf_hist_sina({sym})")
    if err:
        errors.append(f"sina: {err}")
    if df is not None and len(df) > 0:
        return normalise(df, "sina"), "sina", None

    return pd.DataFrame(columns=BAR_COLS), "", "; ".join(errors) if errors else "empty response"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    frames: list[pd.DataFrame] = []
    per_code: dict[str, dict] = {}
    failures: list[dict] = []

    print(f"akshare {ak.__version__} | window {START_DATE}..{END_DATE} | {len(UNIVERSE)} codes\n")

    for sleeve, code in UNIVERSE:
        print(f"-> {code} ({sleeve})", file=sys.stderr)
        try:
            frame, source, err = fetch_code(code)
        except Exception as exc:  # noqa: BLE001
            frame, source, err = pd.DataFrame(columns=BAR_COLS), "", f"{type(exc).__name__}: {exc}"
            traceback.print_exc()

        rows = int(len(frame))
        if rows == 0:
            status = "empty"
        elif rows < SHORT_HISTORY_ROWS:
            status = "short"
        else:
            status = "ok"

        if rows:
            frame = frame.copy()
            frame["code"] = code
            frames.append(frame)

        entry = {
            "sleeve": sleeve,
            "rows": rows,
            "first_date": str(frame["date"].iloc[0]) if rows else None,
            "last_date": str(frame["date"].iloc[-1]) if rows else None,
            "source": source or None,
            "volume_unit": VOLUME_UNIT.get(source),
            "status": status,
            "error_message": err,
        }
        per_code[code] = entry
        if status in ("empty", "error"):
            failures.append({"code": code, "status": status, "error_message": err})

    if frames:
        all_bars = pd.concat(frames, ignore_index=True)
        all_bars["date"] = all_bars["date"].astype(str)
        all_bars["code"] = all_bars["code"].astype(str)
        for col in NUMERIC_COLS:
            all_bars[col] = pd.to_numeric(all_bars[col], errors="coerce").astype("float64")
        all_bars = all_bars.sort_values(["code", "date"], kind="mergesort").reset_index(drop=True)
        all_bars = all_bars[FINAL_COLS]
    else:
        all_bars = pd.DataFrame(
            {
                "code": pd.Series(dtype="object"),
                "date": pd.Series(dtype="object"),
                **{c: pd.Series(dtype="float64") for c in NUMERIC_COLS},
            }
        )[FINAL_COLS]

    all_bars.to_parquet(PARQUET_PATH, engine="pyarrow", compression="snappy", index=False)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "akshare_version": ak.__version__,
        "parameters": {
            "window_start": START_DATE,
            "window_end": END_DATE,
            "period": "daily",
            "adjust": "",
            "short_history_threshold": SHORT_HISTORY_ROWS,
            "sources": ["eastmoney:fund_etf_hist_em", "sina:fund_etf_hist_sina"],
        },
        "row_count": int(len(all_bars)),
        "code_count": len(UNIVERSE),
        "first_date": str(all_bars["date"].min()) if len(all_bars) else None,
        "last_date": str(all_bars["date"].max()) if len(all_bars) else None,
        "parquet_path": str(PARQUET_PATH),
        "per_code": per_code,
        "failures": failures,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # compact stdout table
    hdr = f"{'code':<8}{'sleeve':<11}{'rows':>7}  {'first_date':<12}{'last_date':<12}{'source':<10}{'status'}"
    print(hdr)
    print("-" * len(hdr))
    for code, e in per_code.items():
        print(
            f"{code:<8}{e['sleeve']:<11}{e['rows']:>7}  "
            f"{(e['first_date'] or '-'):<12}{(e['last_date'] or '-'):<12}"
            f"{(e['source'] or '-'):<10}{e['status']}"
        )
    print("-" * len(hdr))
    print(f"TOTAL rows={len(all_bars)}  span={manifest['first_date']}..{manifest['last_date']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
