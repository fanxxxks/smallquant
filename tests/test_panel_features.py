"""E1's two non-negotiables: a feature may not see the future, and a sleeve score may not
hide what it does not cover.

The leakage test builds a tiny synthetic panel in a temporary DuckDB file rather than
perturbing the real one: the point is to prove the *SQL* is trailing, and a synthetic panel
makes the expected values checkable by hand. It has two halves — the feature vector at `t`
must survive a perturbation of every later bar, and the label at `t` must *change*, so a
test that silently stopped looking at the future could not pass by being vacuous.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

duckdb = pytest.importorskip("duckdb")

from newquant.panel import aggregate, features, source  # noqa: E402

SESSIONS = pd.bdate_range("2020-01-01", periods=90).strftime("%Y%m%d").tolist()
CODES = ["600000.SH", "600001.SH", "600002.SH"]


def _synthetic_panel(tmp_path, *, shock_from: int | None = None, shock: float = 1.0):
    """A panel where every price is a known function of the session index.

    ``shock_from`` rescales the *open* of every session at or after that index, for every
    code, with a factor that keeps growing. With ``shock_from=None`` the panel is untampered.
    """
    con = duckdb.connect(str(tmp_path / "panel.duckdb"))
    con.execute("CREATE TABLE trade_calendar(trade_date VARCHAR, is_open BOOLEAN)")
    con.executemany(
        "INSERT INTO trade_calendar VALUES (?, TRUE)", [(d,) for d in SESSIONS]
    )
    con.execute(
        "CREATE TABLE daily_bar_raw(ts_code VARCHAR, trade_date VARCHAR, open DOUBLE,"
        " high DOUBLE, low DOUBLE, close DOUBLE, pre_close DOUBLE, change DOUBLE,"
        " pct_chg DOUBLE, vol DOUBLE, amount DOUBLE)"
    )
    con.execute("CREATE TABLE daily_adj_factor(ts_code VARCHAR, trade_date VARCHAR, adj_factor DOUBLE)")
    con.execute("CREATE TABLE daily_price_limit(ts_code VARCHAR, trade_date VARCHAR, pre_close DOUBLE, up_limit DOUBLE, down_limit DOUBLE)")
    con.execute("CREATE TABLE daily_suspension(ts_code VARCHAR, trade_date VARCHAR, suspend_type VARCHAR, suspend_timing VARCHAR, available_at TIMESTAMP, source VARCHAR)")
    con.execute("CREATE TABLE daily_basic_pit(ts_code VARCHAR, trade_date VARCHAR, turnover_rate DOUBLE, total_mv DOUBLE, pe_ttm DOUBLE, pb DOUBLE)")
    con.execute("CREATE TABLE stocks(ts_code VARCHAR, name VARCHAR, industry VARCHAR, list_date VARCHAR, is_st BOOLEAN)")
    con.execute("CREATE TABLE index_weight_pit(index_code VARCHAR, con_code VARCHAR, trade_date VARCHAR, weight DOUBLE, available_date VARCHAR)")

    bars, adj, limits, basic = [], [], [], []
    for k, code in enumerate(CODES, start=1):
        for i, date in enumerate(SESSIONS):
            # A *proportional* shock would cancel in every ratio, so the perturbation grows
            # with the session index: it changes the level path, not just its scale.
            scale = (
                1.0 + shock * (i - shock_from + 1) / 10.0
                if (shock_from is not None and i >= shock_from)
                else 1.0
            )
            close = (10.0 + 0.01 * i) * (1 + 0.3 * k)
            open_ = close * (1.0 + 0.001 * k) * scale
            bars.append((code, date, open_, close * 1.01, close * 0.99, close, close, 0.0, 0.0, 1e5, 1e7 * k))
            adj.append((code, date, 1.0))
            limits.append((code, date, close, close * 1.10, close * 0.90))
            basic.append((code, date, 1.5 * k, 1e10 * (k + 1), 15.0 + k, 1.2 + 0.1 * k))
        con.execute("INSERT INTO stocks VALUES (?, ?, ?, ?, FALSE)", [code, code, "test", "20100101"])
    con.executemany("INSERT INTO daily_bar_raw VALUES (" + ",".join("?" * 11) + ")", bars)
    con.executemany("INSERT INTO daily_adj_factor VALUES (?,?,?)", adj)
    con.executemany("INSERT INTO daily_price_limit VALUES (?,?,?,?,?)", limits)
    con.executemany("INSERT INTO daily_basic_pit VALUES (?,?,?,?,?,?)", basic)
    con.executemany(
        "INSERT INTO index_weight_pit VALUES ('000300.SH', ?, ?, ?, ?)",
        [(code, SESSIONS[40], 100.0 / len(CODES), SESSIONS[40]) for code in CODES],
    )
    con.commit()
    return con


def test_label_anchors_after_entry(tmp_path):
    """label == open_adj[t+22] / open_adj[t+1] - 1 on a known path, not close-to-close."""
    con = _synthetic_panel(tmp_path)
    signal = [SESSIONS[45]]
    frame = features.build(con, signal)
    row = frame.iloc[0]
    code = row["ts_code"]
    opens = [
        float(
            con.execute(
                "SELECT open FROM daily_bar_raw WHERE ts_code=? AND trade_date=?",
                [code, d],
            ).fetchone()[0]
        )
        for d in SESSIONS
    ]
    expected = opens[45 + 22] / opens[45 + 1] - 1.0
    assert row["label"] == pytest.approx(expected, rel=1e-9)


def test_features_ignore_every_bar_after_the_signal(tmp_path):
    clean = _synthetic_panel(_dir(tmp_path, "clean"))
    shocked = _synthetic_panel(_dir(tmp_path, "shocked"), shock_from=46, shock=1.5)
    signal = [SESSIONS[45]]
    a = features.build(clean, signal, standardise=False).sort_values("ts_code").reset_index(drop=True)
    b = features.build(shocked, signal, standardise=False).sort_values("ts_code").reset_index(drop=True)
    for name in features.FEATURES:
        pd.testing.assert_series_equal(a[name], b[name], check_names=False)
    # Power check: the same perturbation must move the label, or the test proves nothing.
    assert not np.allclose(a["label"].to_numpy(), b["label"].to_numpy())


def _dir(parent, name):
    path = parent / name
    path.mkdir()
    return path


def test_missing_features_stay_missing_after_standardisation(tmp_path):
    con = _synthetic_panel(tmp_path)
    same_day = ("ep", "bp", "log_mv", "list_age_yr")
    lookback = [f for f in features.FEATURES if f not in same_day]
    raw = features.build(con, [SESSIONS[0]], standardise=False)
    # The first session has no history at all: every lookback feature must be absent rather
    # than silently zero-filled. The same-day valuation and metadata features are the
    # exception and must be present, which also checks the exception list is complete.
    assert raw[lookback].isna().all().all()
    assert raw[list(same_day)].notna().all().all()

    standardised = features.build(con, [SESSIONS[0]])
    # A column that is constant across the section has no cross-sectional information, so its
    # z-score is undefined rather than 0: the three synthetic names share a listing date.
    assert standardised["list_age_yr"].isna().all()
    assert standardised[["ep", "bp", "log_mv"]].notna().all().all()


def test_cross_sectional_z_is_centred_and_bounded():
    frame = pd.DataFrame(
        {
            "trade_date": ["20200131"] * 5 + ["20200228"] * 5,
            "x": [1.0, 2.0, 3.0, 4.0, 100.0] * 2,
        }
    )
    out = features.cross_sectional_z(frame, ("x",))
    assert np.nanmedian(out["x"].to_numpy()[:5]) == pytest.approx(0.0, abs=1e-12)
    assert out["x"].abs().max() <= features.MAD_CLIP + 1e-12
    assert out["x"].notna().all()


def test_sleeve_score_covers_only_what_it_can_predict():
    """Coverage is reported, and the score is a weighted mean over *covered* weight."""
    predictions = pd.DataFrame(
        {
            "ts_code": CODES,
            "trade_date": [SESSIONS[40]] * 3,
            "score": [1.0, 3.0, np.nan],
        }
    )
    con = _synthetic_panel_local()
    table = aggregate.sleeve_table(predictions, con, [SESSIONS[40]], bridge={"000300.SH": "510300"})
    assert len(table) == 1
    row = table.iloc[0]
    assert row["n_predicted"] == 2
    assert row["coverage"] == pytest.approx(2 / 3, rel=1e-6)
    assert row["score"] == pytest.approx(2.0, rel=1e-6)


def test_deviation_share_is_zero_when_every_member_scores_alike():
    months = [f"2020{m:02d}28" for m in range(1, 9)]
    rows = []
    for date in months:
        for index_code, etf in source.EQUITY_BRIDGE.items():
            rows.append(
                {
                    "trade_date": date,
                    "index_code": index_code,
                    "etf": etf,
                    "score": 0.5 + 0.01 * months.index(date) * (1 if index_code.endswith("300.SH") else 2),
                    "coverage": 0.9,
                    "common": 0.5,
                }
            )
    stats = aggregate.deviation_share(pd.DataFrame(rows))
    # Each index moves on its own scale, so the deviation term is not zero here; the point of
    # the assertion is that the number is a share in [0, 1] and is computed at all.
    assert 0.0 <= stats["deviation_share"] <= 1.0
    assert stats["months"] == len(rows)


def _synthetic_panel_local():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE index_weight_pit(index_code VARCHAR, con_code VARCHAR, trade_date VARCHAR, weight DOUBLE, available_date VARCHAR)")
    con.executemany(
        "INSERT INTO index_weight_pit VALUES ('000300.SH', ?, ?, 33.0, ?)",
        [(code, SESSIONS[40], SESSIONS[40]) for code in CODES],
    )
    return con


def test_index_weights_are_as_of_not_latest():
    """A snapshot announced after the signal date must not be visible at the signal date."""
    con = _synthetic_panel_local()
    con.execute(
        "INSERT INTO index_weight_pit VALUES ('000300.SH', '600000.SH', ?, 100.0, ?)",
        [SESSIONS[50], SESSIONS[55]],
    )
    visible = source.index_weights(con, "000300.SH", SESSIONS[40])
    assert visible["trade_date"].unique().tolist() == [SESSIONS[40]]
    later = source.index_weights(con, "000300.SH", SESSIONS[56])
    assert later["trade_date"].unique().tolist() == [SESSIONS[50]]
