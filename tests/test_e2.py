"""E2 — the executor path and the replay arithmetic, pinned before the numbers are trusted.

These tests exist because the report in `evidence/e2-report.md` is only as good as the two
things it rests on: (a) a split or a dividend moves NAV by exactly the amount it should, and
(b) the net-CNY difference and its interval are computed in the units the pre-registration
names. Neither is visible in the summary table, so both are pinned here.
"""

import math
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from newquant.eval import e2
from newquant.ledger import Book, LedgerStore
from newquant.order import plan_order
from newquant.venue import ETF_STD, Instrument, gate_ok, min_notional

EQ = Instrument(code="512100", name="中证1000ETF", klass="equity")
BOND = Instrument(code="511220", name="城投债ETF", klass="bond")


def make_book(tmp_path, name="e2.jsonl", cash="75000"):
    store = LedgerStore(tmp_path / name, now="2026-11-04T00:00:00+00:00")
    book = Book(store, instruments={EQ.code: EQ, BOND.code: BOND})
    if not store.records:
        book.open(Decimal(cash))
    return book


class TestSplitContinuity:
    """I-5: a unit change moves lots, never NAV."""

    def test_reverse_split_preserves_nav_and_pays_the_fraction(self, tmp_path):
        book = make_book(tmp_path)
        # 512100 2022-09-05: raw 0.982 -> 2.713, solved ratio 0.365708 (100 -> 36.57 shares).
        # The mark that must leave NAV unchanged is the pre-split close; the engine derives the
        # post-split price as close/ratio, so the test uses the same derivation.
        ratio = Decimal("0.365708")
        raw_prev = Decimal("0.982")
        raw_after = raw_prev / ratio
        book.execute(code="512100", side="buy", lots=3, price=raw_prev, session=1)
        before = book.nav({"512100": raw_prev, "511220": Decimal("0")})
        new_lots = int(Decimal(3) * ratio)  # 1
        residual = (Decimal(3) * ratio - new_lots) * 100 * raw_after
        book.corporate_action(code="512100", action="split", session=2, ratio=ratio,
                              residual_cash=residual.quantize(Decimal("0.01")))
        after = book.nav({"512100": raw_after, "511220": Decimal("0")})
        assert book.positions["512100"] == new_lots
        assert abs(after - before) <= Decimal("0.05")

    def test_truncation_without_residual_cash_loses_nav(self, tmp_path):
        """The bug the residual exists to prevent: 3 lots -> 1 lot evaporates 0.097 lots."""
        ratio = Decimal("0.365708")
        raw_prev = Decimal("0.982")
        raw_after = raw_prev / ratio
        book = make_book(tmp_path)
        book.execute(code="512100", side="buy", lots=3, price=raw_prev, session=1)
        before = book.nav({"512100": raw_prev})
        book.corporate_action(code="512100", action="split", session=2, ratio=ratio)
        assert book.nav({"512100": raw_after}) < before - Decimal("20")


class TestDividendCredit:
    def test_dividend_adds_cash_and_leaves_positions_alone(self, tmp_path):
        book = make_book(tmp_path)
        book.execute(code="511220", side="buy", lots=2, price=Decimal("95.00"), session=1)
        cash_before, lots_before = book.cash, book.positions["511220"]
        book.corporate_action(code="511220", action="dividend", session=2,
                              per_share=Decimal("6.00"))
        assert book.positions["511220"] == lots_before
        assert book.cash - cash_before == Decimal("6.00") * lots_before * 100


class TestCostGateArithmetic:
    """I-3: the floor is a commission floor, so it binds on small orders only."""

    def test_inherited_five_bp_clears_near_5000(self):
        expected = min_notional(Decimal("15.1"), "buy", ETF_STD)
        assert expected is not None
        assert Decimal("4600") < expected < Decimal("5200")
        assert not gate_ok(expected - Decimal("1"), "buy", Decimal("15.1"), ETF_STD)[0]
        assert gate_ok(expected, "buy", Decimal("15.1"), ETF_STD)[0]

    def test_measured_slippage_clears_lower_than_the_constant(self):
        """511220 at 0.05 bp of measured slip needs a smaller order than at 5 bp."""
        cheap = ETF_STD.__class__(slippage_rate=Decimal("0.000005"), name="measured")
        assert min_notional(Decimal("15.1"), "buy", cheap) < Decimal("4000")

    def test_a_delta_below_one_lot_is_not_a_gate_event(self):
        plan = plan_order(EQ, side="buy", target_notional=Decimal("30"),
                          price=Decimal("2.713"), tolerance_bp=Decimal("15.1"))
        assert plan.reason == "zero_lot"
        assert plan.lots == 0
        # I-2: an order that is not placed carries no cost object at all, so nothing is charged.
        assert plan.cost is None


class TestDeltaArithmetic:
    """The pre-registered measure: annualised net CNY with its interval and its MDE."""

    @staticmethod
    def _frame(navs, dtype=float):
        dates = [f"{2016 + i // 12}-{i % 12 + 1:02d}-28" for i in range(len(navs))]
        return pd.DataFrame({"date": dates, "nav": [float(v) for v in navs]})

    def test_constant_annual_gap_becomes_that_gap_per_year(self):
        nav0 = Decimal(75000)
        static = self._frame([Decimal(75000) * (Decimal("1.004") ** (i + 1)) for i in range(120)])
        arm = self._frame([Decimal(75000) * (Decimal("1.008") ** (i + 1)) for i in range(120)])
        delta = e2._delta_series(static, arm, nav0)
        block = e2._cny_block(delta)
        assert len(delta) == 120
        # 0.4 % of 75 000 per month = 300 CNY/month = 3 600 CNY/yr, exactly, by construction
        assert block["annual_cny"] == pytest.approx(12 * 300.0, rel=1e-3)
        assert block["cumulative_cny"] == pytest.approx(120 * 300.0, rel=1e-3)

    def test_identical_arms_give_a_zero_delta(self):
        frame = self._frame([Decimal(75000) * (Decimal("1.005") ** (i + 1)) for i in range(120)])
        block = e2._cny_block(e2._delta_series(frame, frame, Decimal(75000)))
        assert block["annual_cny"] == pytest.approx(0.0, abs=1e-9)
        assert block["mde_annual_cny"] == pytest.approx(0.0, abs=1e-9)

    def test_mde_is_the_declared_multiple_of_the_standard_error(self):
        rng = np.random.default_rng(7)
        nav0 = Decimal(75000)
        base = np.cumprod(1 + rng.normal(0.004, 0.003, 120))
        static = self._frame([Decimal(75000) * Decimal(f"{v:.10f}") for v in base])
        arm = self._frame([Decimal(75000) * Decimal(f"{v * (1 + 1e-4 * i):.10f}")
                           for i, v in enumerate(base)])
        delta = e2._delta_series(static, arm, nav0)
        block = e2._cny_block(delta)
        sd = float(np.std(delta.to_numpy(), ddof=1))
        assert block["mde_annual_cny"] == pytest.approx(
            2.8 * sd * math.sqrt(12) / math.sqrt(10), rel=1e-6)

    def test_interval_is_ordered_and_covers_the_point_estimate(self):
        rng = np.random.default_rng(11)
        nav0 = Decimal(75000)
        base = np.cumprod(1 + rng.normal(0.004, 0.004, 120))
        static = self._frame([Decimal(75000) * Decimal(f"{v:.10f}") for v in base])
        drift = np.cumprod(1 + rng.normal(0.004, 0.004, 120)) * (1.0015 ** np.arange(120))
        arm = self._frame([Decimal(75000) * Decimal(f"{v:.10f}") for v in drift])
        block = e2._cny_block(e2._delta_series(static, arm, nav0))
        assert block["annual_cny_lo"] <= block["annual_cny"] <= block["annual_cny_hi"]


class TestVerdictLogic:
    @staticmethod
    def _primary(annual, lo, hi, mde, static_fills=10, gate=0.8, n_intents=102):
        return {
            "arms": {"static": {"n_fills": static_fills, "n_intents": n_intents,
                                "suppressed_by_reason": {"below_cost_gate": int(gate * n_intents)}}},
            "delta_vol": {"annual_cny": annual, "annual_cny_lo": lo, "annual_cny_hi": hi,
                          "mde_annual_cny": mde},
            "delta_rule": {"annual_cny": annual, "annual_cny_lo": lo, "annual_cny_hi": hi,
                           "mde_annual_cny": mde},
        }

    def test_interval_containing_zero_is_not_adopted(self):
        verdict = e2._verdict(self._primary(500.0, -100.0, 1200.0, 400.0))
        assert verdict["clauses"]["vol"]["adopt"] is False
        assert verdict["clauses"]["vol"]["ci_excludes_zero"] is False

    def test_clean_interval_below_the_threshold_is_not_adopted(self):
        verdict = e2._verdict(self._primary(200.0, 50.0, 400.0, 300.0))
        assert verdict["clauses"]["vol"]["ci_excludes_zero"] is True
        assert verdict["clauses"]["vol"]["point_above_threshold"] is False
        assert verdict["clauses"]["vol"]["adopt"] is False

    def test_large_mde_blocks_adoption_even_with_a_clean_interval(self):
        verdict = e2._verdict(self._primary(600.0, 100.0, 1100.0, 900.0))
        assert verdict["clauses"]["vol"]["mde_exceeds_threshold"] is True
        assert verdict["clauses"]["vol"]["adopt"] is False
        assert "unmeasurable" in verdict["reading"]

    def test_a_frozen_baseline_makes_the_edge_a_gate_artefact(self):
        verdict = e2._verdict(self._primary(900.0, 200.0, 1600.0, 300.0))
        assert verdict["primary_baseline_frozen_by_gate"] is True
        assert verdict["clauses"]["vol"]["adopt"] is True
        assert "frozen" in verdict["reading"]
