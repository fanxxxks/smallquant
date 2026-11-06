"""Hand-computed arithmetic tests. These are the cases the reviews said catch real bugs:
the 16.00 CNY / 4,800-5,000-5,100 suppression, the 6,400 first-clearing size, a 0-lot order
paying nothing, a 150-share sell trading 100, and a T+1 buy that cannot be sold same session.
"""

from decimal import Decimal

import pytest

from newquant.venue import ETF_STD, Instrument, gate_ok, min_notional, q, round_to_lots

EQ = Instrument(code="510300", name="沪深300ETF", klass="equity")
BOND = Instrument(code="511010", name="国债ETF", klass="bond")


class TestCostArithmetic:
    def test_commission_floor_binds_below_20000(self):
        cost = ETF_STD.cost(Decimal("4800"), "buy")
        assert cost.commission == Decimal("5.00")
        assert cost.transfer == Decimal("0.05")  # 4800 * 1e-05 = 0.048 -> 0.05
        assert cost.slippage == Decimal("2.40")
        assert cost.total == Decimal("7.45")
        assert cost.bp.quantize(Decimal("0.01")) == Decimal("15.52")

    def test_above_floor_uses_the_rate(self):
        cost = ETF_STD.cost(Decimal("100000"), "buy")
        assert cost.commission == Decimal("25.00")
        assert cost.bp.quantize(Decimal("0.01")) == Decimal("7.60")

    def test_etf_sell_pays_no_stamp_duty(self):
        buy = ETF_STD.cost(Decimal("10000"), "buy")
        sell = ETF_STD.cost(Decimal("10000"), "sell")
        assert sell.stamp == Decimal("0.00")
        assert sell.total == buy.total

    def test_zero_notional_pays_nothing_because_it_never_executes(self):
        with pytest.raises(ValueError):
            ETF_STD.cost(Decimal("0"), "buy")

    def test_min_notional_matches_the_published_table(self):
        # tolerance -> smallest order whose one-way TOTAL cost clears it (architecture doc §5)
        assert min_notional(Decimal("10"), "buy") == Decimal("10204.09")
        assert min_notional(Decimal("15.1"), "buy") == Decimal("5000.00")
        assert min_notional(Decimal("30"), "buy") == Decimal("2008.04")
        assert min_notional(Decimal("50"), "buy") == Decimal("1114.00")

    def test_the_rate_floor_is_seven_point_six_bp(self):
        # commission_rate + transfer + slippage; no order, at any size, goes below it
        assert ETF_STD.cost(Decimal("20000"), "buy").bp.quantize(Decimal("0.01")) == Decimal("7.60")
        assert min_notional(Decimal("7.6"), "buy") == Decimal("20000.00")
        assert min_notional(Decimal("7.5"), "buy") is None
        assert min_notional(Decimal("5"), "buy") is None

    @pytest.mark.parametrize("tol", ["7.6", "8", "10", "15.1", "30", "50", "120"])
    def test_the_bound_passes_its_own_gate_and_a_tenth_smaller_does_not(self, tol):
        bound = min_notional(Decimal(tol), "buy")
        assert bound is not None
        passes, bp = gate_ok(bound, "buy", Decimal(tol))
        assert passes, f"{tol} bp bound {bound} came out at {bp}"
        smaller = (bound * Decimal("0.9")).quantize(Decimal("0.01"), rounding="ROUND_CEILING")
        assert not gate_ok(smaller, "buy", Decimal(tol))[0]

    def test_the_bound_shrinks_as_the_tolerance_widens(self):
        grid = [Decimal(t) for t in ("7.6", "8", "10", "15.1", "30", "50", "120")]
        bounds = [min_notional(t, "buy") for t in grid]
        assert all(b is not None for b in bounds)
        assert bounds == sorted(bounds, reverse=True)


class TestLotRounding:
    def test_4800_5000_5100_all_floor_to_4800(self):
        for target in ("4800", "5000", "5100"):
            assert round_to_lots(Decimal(target), Decimal("16.00"), 100) == 3

    def test_6400_is_the_first_clearing_size(self):
        assert round_to_lots(Decimal("6400"), Decimal("16.00"), 100) == 4
        passes, bp = gate_ok(Decimal("6400"), "buy", Decimal("15.1"))
        assert passes
        assert bp.quantize(Decimal("0.01")) == Decimal("12.91")

    def test_150_share_sell_trades_one_lot(self):
        assert round_to_lots(Decimal("2400"), Decimal("16.00"), 100) == 1

    def test_rounding_never_rounds_up(self):
        assert round_to_lots(Decimal("6399.99"), Decimal("16.00"), 100) == 3


class TestGate:
    @pytest.mark.parametrize("notional", ["4800", "5000", "5100"])
    def test_suppressed_at_ten_bp_tolerance(self, notional):
        # every size the 16.00 price can produce from a 5,000-ish intent is under 10,204.09
        assert round_to_lots(Decimal(notional), Decimal("16.00"), 100) == 3
        passes, bp = gate_ok(Decimal("4800"), "buy", Decimal("10"))
        assert not passes
        assert bp > Decimal("10")

    def test_pre_rounding_test_would_have_passed(self):
        # 5,000 desired passes a pre-rounding check (10.0 bp) but executes at 4,800 = 15.52 bp
        assert Decimal("5.00") / Decimal("5000") * Decimal(10000) <= Decimal("10")
        passes, _ = gate_ok(Decimal("4800"), "buy", Decimal("10"))
        assert not passes

    def test_gate_is_inclusive_at_the_boundary(self):
        passes, bp = gate_ok(Decimal("5000"), "buy", Decimal("15.1"))
        assert passes, bp
        assert bp.quantize(Decimal("0.01")) == Decimal("15.10")


class TestSettlementFacts:
    def test_settlement_is_per_class_not_uniform(self):
        assert EQ.settle_days == 1
        assert BOND.settle_days == 0

    def test_money_quantises_half_up(self):
        assert q("0.005") == Decimal("0.01")
        assert q("2.675") == Decimal("2.68")
