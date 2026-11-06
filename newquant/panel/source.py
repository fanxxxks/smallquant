"""Read-only access to the L0 panel and the two as-of tables E1 needs.

The panel is `ashare_v2.duckdb` (28 tables, 2014-01-02 … 2026-10-15). E1 uses seven
of them:

  daily_bar_raw        open/high/low/close/amount, raw prices
  daily_adj_factor     adj_factor, one row per (code, date) that has a bar
  daily_price_limit    up_limit/down_limit, the entry gate
  daily_suspension     suspend_type in {S, R}; a suspended name cannot be entered
  daily_basic_pit      turnover_rate, total_mv, pe_ttm, pb
  index_weight_pit     (index, member, trade_date, weight, available_date)
  trade_calendar       the session axis, and therefore the signal dates

Nothing else in the project opens this file. A second connection would be a second
notion of the panel; `connect()` exists so there is exactly one.
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pandas as pd

DEFAULT_PANEL = os.environ.get(
    "NEWQUANT_PANEL", "D:/minequant/AlphaGPT/data/ashare_v2.duckdb"
)

# E1 predicts the equity sleeve only: those are the three indices with a point-in-time
# weight bridge, and the ETFs that track them. 399006.SZ (159915) has no weight series
# in the panel, so the ChiNext ETF is outside E1 by data, not by choice.
EQUITY_BRIDGE = {
    "000300.SH": "510300",
    "000905.SH": "510500",
    "000852.SH": "512100",
}


def connect(
    path: str | Path | None = None,
    memory_limit: str = "1500MB",
    temp_dir: str | Path | None = None,
) -> duckdb.DuckDBPyConnection:
    """One read-only connection with a bounded memory budget and a spill directory.

    The host had ~2.9 GB free when this was written and the bar table is 12 M rows, so a
    window function over the whole history cannot be held in memory; DuckDB is told where to
    spill instead of being allowed to fail. `preserve_insertion_order=false` is what makes a
    large ORDER BY inside a window cheap — the rows are re-sorted anyway.
    """
    con = duckdb.connect(str(path or DEFAULT_PANEL), read_only=True)
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute("SET threads=4")
    con.execute("SET preserve_insertion_order=false")
    spill = Path(temp_dir or os.environ.get("NEWQUANT_SPILL", ".duckdb_tmp"))
    spill.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory='{spill.resolve().as_posix()}'")
    return con


def index_member_universe(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Every stock that has ever appeared in an index E1 can bridge to an ETF.

    3 634 names against the panel's 5 820. E1 trains and scores on this population rather than
    the full market: the sleeve score is a weighted mean over index members, so a stock that
    has never been a member can only dilute the fit. Recorded as a scope decision, not a
    convenience — the panel IC this experiment reports is the IC on the scored population.
    """
    rows = con.execute(
        "SELECT DISTINCT con_code FROM index_weight_pit ORDER BY 1"
    ).fetchall()
    return [r[0] for r in rows]


def signal_dates(con: duckdb.DuckDBPyConnection, start: str = "20140101", end: str = "20251231") -> list[str]:
    """Last open session of each month — the E1 decision dates.

    Monthly because the panel is monthly: the weight files are month-end snapshots, so a
    finer signal date would be decorated with a coarser as-of view and pretend otherwise.
    """
    rows = con.execute(
        """
        SELECT max(trade_date) AS d
        FROM trade_calendar
        WHERE is_open AND trade_date BETWEEN ? AND ?
        GROUP BY substr(trade_date, 1, 6)
        ORDER BY d
        """,
        [start, end],
    ).fetchall()
    return [r[0] for r in rows]


def index_weights(
    con: duckdb.DuckDBPyConnection, index_code: str, as_of: str
) -> pd.DataFrame:
    """Point-in-time index weights visible at `as_of`.

    Two constraints, both learned the hard way from the panel's own metadata: a weight
    row is only *knowable* from its `available_date` (median 3 calendar days after the
    snapshot, max 12), and the snapshot that is visible is the **latest one announced on
    or before** `as_of` — not the largest `trade_date`, which would leak the next month's
    membership into this month's score.
    """
    return con.execute(
        """
        WITH vis AS (
            SELECT trade_date, con_code, weight, available_date
            FROM index_weight_pit
            WHERE index_code = ? AND trade_date <= ? AND available_date <= ?
        )
        SELECT con_code, weight, trade_date, available_date
        FROM vis
        WHERE trade_date = (SELECT max(trade_date) FROM vis)
        """,
        [index_code, as_of, as_of],
    ).df()


def panel_dates(con: duckdb.DuckDBPyConnection) -> tuple[str, str]:
    """Coverage of the bar table, so a caller can state its own window honestly."""
    row = con.execute("SELECT min(trade_date), max(trade_date) FROM daily_bar_raw").fetchone()
    return row[0], row[1]
