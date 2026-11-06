"""The E1 input contract for the A-share panel.

E1 (docs/direction-architecture.md:256-303) predicts the equity sleeve only and joins
stock-level predictions to the traded ETFs through point-in-time index weights. That
claim rests on properties of the panel, not on the model, so they are pinned here:
if the panel is re-ingested and one of them changes, the failure belongs to the input
and must surface before a fold runs, not as an unexplained IC.

The panel is an external read-only input (never written by this project), so the whole
module skips when it is absent rather than failing a checkout that lacks it.
"""

from __future__ import annotations

import pytest

pytest.importorskip("duckdb")

PANEL = "D:/minequant/AlphaGPT/data/ashare_v2.duckdb"

# E1's evaluation window and the indices that have both weights and a traded ETF.
EVAL_START, EVAL_END = "20160101", "20251231"
SLEEVE_INDICES = ("000300.SH", "000905.SH", "000852.SH")
# 159915 (创业板ETF) is traded but has no point-in-time weight source; E1 excludes it.
NO_BRIDGE_CODE = "399006.SZ"


@pytest.fixture(scope="module")
def panel():
    duckdb = pytest.importorskip("duckdb")
    connection = duckdb.connect(PANEL, read_only=True)
    yield connection
    connection.close()


def rows(panel, sql, params=None):
    return panel.execute(sql, params or []).fetchall()


def scalar(panel, sql, params=None):
    return rows(panel, sql, params)[0][0]


def test_only_the_three_bridged_indices_carry_weights(panel):
    """A fourth index in the table would widen E1's scope; a missing one would break it."""
    codes = [r[0] for r in rows(panel, "select distinct index_code from index_weight_pit order by 1")]
    assert set(SLEEVE_INDICES) <= set(codes), f"missing weights for {set(SLEEVE_INDICES) - set(codes)}"
    assert len(codes) == 3, f"index_weight_pit carries {codes}, not only the three bridged indices"
    assert NO_BRIDGE_CODE not in codes, "a weight source for 399006.SZ changes E1's scope"


def test_weights_are_monthly_not_daily(panel):
    """The bridge is monthly; a daily series would change what a fold may use."""
    for code in SLEEVE_INDICES:
        per_month = scalar(
            panel,
            """select max(n) from (
                 select substr(trade_date, 1, 6) ym, count(distinct trade_date) n
                 from index_weight_pit where index_code = ? group by 1)""",
            [code],
        )
        assert per_month == 1, f"{code} has {per_month} weight dates in some month"


def test_weights_are_available_after_the_effective_date(panel):
    """E1 must join on available_date: the effective date is not knowable on that date."""
    lag_min, lag_median, lag_max = rows(
        panel,
        """select min(d), median(d), max(d) from (
             select datediff('day', strptime(trade_date, '%Y%m%d'), strptime(available_date, '%Y%m%d')) d
             from index_weight_pit)""",
    )[0]
    assert lag_min >= 1, "a weight available on its own effective date is look-ahead"
    assert 1 <= lag_median <= 10, f"median publication lag {lag_median}d is outside the observed 1-10d"
    assert lag_max <= 31, f"max publication lag {lag_max}d exceeds one month of drift"


def test_weights_sum_to_a_full_index_inside_the_evaluation_window(panel):
    """Rounded names leave a little off 100; a sum near 50 means partial membership.

    The early months of 000300.SH and 000905.SH sum to 98.5 (17 dates, all 2005-2006),
    which is partial coverage of that era rather than corruption: they sit outside
    E1's folds, and the test below keeps them there instead of quietly tolerating them.
    """
    worst, worst_where = rows(
        panel,
        """select min(s), arg_min(concat(index_code, ' ', trade_date), s) from (
             select index_code, trade_date, sum(weight) s from index_weight_pit
             where trade_date >= ? group by 1, 2)""",
        [EVAL_START],
    )[0]
    assert 99.0 <= worst <= 101.0, f"{worst_where} weights sum to {worst}, not ~100"

    pre_2010 = scalar(
        panel,
        """select count(*) from (
             select index_code, trade_date, sum(weight) s from index_weight_pit group by 1, 2)
           where s < 99 and trade_date < '20100101'""",
    )
    everywhere = scalar(
        panel,
        """select count(*) from (
             select index_code, trade_date, sum(weight) s from index_weight_pit group by 1, 2)
           where s < 99""",
    )
    assert pre_2010 == everywhere, "a partial weight month appeared inside the evaluation era"


def test_adjustment_factor_is_present_so_returns_are_total_return(panel):
    """Without adj_factor a dividend month would enter the label as a loss."""
    nulls = scalar(panel, "select count(*) from daily_bar where adj_factor is null or adj_factor <= 0")
    assert nulls == 0, f"{nulls} daily_bar rows have no usable adj_factor"


def test_panel_covers_the_evaluation_window_wide_enough(panel):
    """E1 spans 10 annual folds; the cross-section must be hundreds wide, not dozens."""
    first, last = rows(panel, "select min(trade_date), max(trade_date) from daily_bar")[0]
    assert first <= EVAL_START and last >= EVAL_END, f"panel spans {first}..{last}, short of the folds"
    width = scalar(
        panel,
        """select count(distinct ts_code) from daily_bar
           where trade_date between ? and ?""",
        [EVAL_START, EVAL_END],
    )
    assert width >= 2000, f"only {width} codes in the evaluation window"


def test_tradability_filters_have_their_inputs(panel):
    """A label that ignores limits and suspensions buys stocks it could not have bought."""
    limits = scalar(panel, "select count(*) from daily_price_limit where trade_date between ? and ?",
                    [EVAL_START, EVAL_END])
    bars = scalar(panel, "select count(*) from daily_bar where trade_date between ? and ?",
                  [EVAL_START, EVAL_END])
    assert limits >= 0.95 * bars, f"price limits cover {limits} rows against {bars} bars"
    kinds = {r[0] for r in rows(panel, "select distinct suspend_type from daily_suspension")}
    assert kinds <= {"S", "R"}, f"unexpected suspension types {kinds}"
    assert scalar(panel, "select count(*) from daily_suspension where available_at is null") == 0


def test_the_sleeve_members_can_be_priced_on_the_decision_date(panel):
    """The coverage term exists because some members are missing; it must not be ~everything."""
    matched = scalar(
        panel,
        """select count(*) from index_weight_pit w
           join daily_bar b on b.ts_code = w.con_code and b.trade_date = w.trade_date
           where w.index_code = '000300.SH' and w.trade_date = '20251231'""",
    )
    total = scalar(
        panel,
        """select count(*) from index_weight_pit
           where index_code = '000300.SH' and trade_date = '20251231'""",
    )
    assert total >= 250, f"only {total} weighted members on 2025-12-31"
    assert matched >= 0.95 * total, f"{matched}/{total} members have a bar on the weight date"


def test_settlement_classes_are_declared_in_the_frozen_venue_table():
    """Invariant 9 is only tickable because every traded code carries its settlement class."""
    pd = pytest.importorskip("pandas")
    venue = pd.read_parquet("data/venue.parquet")
    settle = dict(zip(venue["klass"], venue["settle_days"]))
    assert settle.get("equity") == 1 and settle.get("overseas") == 1, settle
    assert settle.get("bond") == 0 and settle.get("cash") == 0 and settle.get("commodity") == 0, settle
