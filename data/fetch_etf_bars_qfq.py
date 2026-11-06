#!/usr/bin/env python
"""Forward-adjusted (qfq) daily bars for the 11 tradable codes — layer-0 input for dividends.

Why this file exists: `data/etf_bars.parquet` is fetched with adjust="" (raw close), which is
what lot rounding and the cost gate must use. A raw series, however, drops on every ex-date,
so a replay on raw prices silently loses the distribution. The qfq series is the same price
path with distributions reinvested into the price, so the pair (raw, qfq) identifies the cash
distribution per share:

    total_return_t = qfq_t / qfq_{t-1}
    D_t = raw_{t-1} * total_return_t - raw_t

`D_t` is the per-share cash distribution on ex-date t (CNY), and it is the number
`Book.corporate_action(action="dividend", per_share=D_t)` needs. Nothing here is assumed:
a code with no distribution produces D_t = 0 on every date.

Output: data/etf_bars_qfq.parquet + data/etf_bars_qfq.manifest.json
Run:    python D:/newquant/data/fetch_etf_bars_qfq.py
"""

from __future__ import annotations

import hashlib
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
PARQUET_PATH = OUT_DIR / "etf_bars_qfq.parquet"
MANIFEST_PATH = OUT_DIR / "etf_bars_qfq.manifest.json"

START_DATE = "20130101"
END_DATE = "20261104"
RETRIES = 3
RETRY_SLEEP = 2.0

# The 11 codes `venue.parquet` marks tradable=True. Non-tradable codes are not traded, so a
# distribution on them cannot reach the account.
CODES = [
    "510300", "510500", "159915", "512100",
    "511220", "511380",
    "518880", "159934",
    "513100", "513500", "159920",
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
NUMERIC_COLS = ["open", "close", "high", "low", "volume", "amount", "amplitude", "pct_chg", "chg", "turnover"]
FINAL_COLS = ["code", "date"] + NUMERIC_COLS


def with_retries(fn, label: str):
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            return fn(), None
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
            print(f"    [retry {attempt}/{RETRIES}] {label}: {last}", file=sys.stderr)
            if attempt < RETRIES:
                time.sleep(RETRY_SLEEP)
    return None, last


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    out = df.rename(columns=EM_RENAME).copy()
    d = out["date"]
    if pd.api.types.is_datetime64_any_dtype(d):
        out["date"] = d.dt.strftime("%Y-%m-%d")
    else:
        out["date"] = pd.to_datetime(d.astype(str), errors="coerce").dt.strftime("%Y-%m-%d")
    for col in NUMERIC_COLS:
        out[col] = pd.to_numeric(out.get(col), errors="coerce").astype("float64")
    return out.dropna(subset=["date"])[["date"] + NUMERIC_COLS].reset_index(drop=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frames: list[pd.DataFrame] = []
    per_code: dict[str, dict] = {}

    print(f"akshare {ak.__version__} | adjust=qfq | {len(CODES)} codes\n")
    for code in CODES:
        print(f"-> {code}", file=sys.stderr)
        try:
            df, err = with_retries(
                lambda: ak.fund_etf_hist_em(
                    symbol=code, period="daily", start_date=START_DATE, end_date=END_DATE, adjust="qfq"
                ),
                f"fund_etf_hist_em({code},qfq)",
            )
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            df, err = None, f"{type(exc).__name__}: {exc}"
        rows = 0 if df is None else int(len(df))
        entry = {
            "rows": rows,
            "first_date": None,
            "last_date": None,
            "status": "ok" if rows else "empty",
            "error_message": err,
        }
        if rows:
            frame = normalise(df)
            frame["code"] = code
            frames.append(frame)
            entry["first_date"] = str(frame["date"].iloc[0])
            entry["last_date"] = str(frame["date"].iloc[-1])
            entry["rows"] = int(len(frame))
        per_code[code] = entry

    if not frames:
        print("no rows fetched", file=sys.stderr)
        return 1

    bars = pd.concat(frames, ignore_index=True)
    bars["date"] = bars["date"].astype(str)
    bars["code"] = bars["code"].astype(str)
    bars = bars.sort_values(["code", "date"], kind="mergesort").reset_index(drop=True)[FINAL_COLS]
    bars.to_parquet(PARQUET_PATH, engine="pyarrow", compression="snappy", index=False)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "akshare_version": ak.__version__,
        "parameters": {
            "window_start": START_DATE,
            "window_end": END_DATE,
            "period": "daily",
            "adjust": "qfq",
            "source": "eastmoney:fund_etf_hist_em",
            "codes": CODES,
        },
        "row_count": int(len(bars)),
        "code_count": int(bars["code"].nunique()),
        "first_date": str(bars["date"].min()),
        "last_date": str(bars["date"].max()),
        "parquet_path": str(PARQUET_PATH),
        "parquet_sha256": sha256(PARQUET_PATH),
        "per_code": per_code,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {PARQUET_PATH} rows={len(bars)} sha256={manifest['parquet_sha256'][:16]}…")
    print(f"wrote {MANIFEST_PATH}")
    for code, e in per_code.items():
        if e["status"] != "ok":
            print(f"  FAILED {code}: {e['error_message']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
