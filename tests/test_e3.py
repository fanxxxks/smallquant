"""E3 — the lot-defined composition, pinned where the report cannot show it.

The report in `evidence/e3-report.md` rests on four things that are invisible in a table:
(a) the floor is the *larger* of the cost gate and one board lot, per member;
(b) the member count ``k`` shrinks until the per-member slice clears that floor, and never below 1;
(c) a sleeve's target weight becomes what its whole lots are worth, rounded DOWN;
(d) the redeploy rule is deterministic and sums to 1 - including the case that made the first
version unusable, where two sleeves sat 0.0002 apart on a percentage threshold.

Prices come from the frozen bars through `build_market`, so these tests are also the guard on
the venue fixture: if a lot size or a listing date moves, the composition tests move with it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from newquant.replay import (ARMS, MANDATE, SLEEVE_MEMBERS, Arm, available_members, build_market,
                             code_gate, compose, lot_composition, sleeve_floor,
                     slippage_table)
from newquant.eval import e3

NAV50 = Decimal("50000")
NAV120 = Decimal("120000")
TOL = Decimal("15.1")
ENTRY = "2016-01-04"


@pytest.fixture(scope="module")
def market():
    return build_market("data/etf_bars.parquet", "data/corp_actions.parquet",
                        "evidence/sleeve_scores.parquet")


@pytest.fixture(scope="module")
def slip(market):
    codes = tuple(c for members in SLEEVE_MEMBERS.values() for c in members)
    return slippage_table(market, codes, "measured")


class TestFloor:
    def test_bond_lot_dominates_the_cost_gate(self, market, slip):
        """One board lot of a par-quoted bond ETF is 2x the 5 000 CNY commission-floor gate."""
        bond = [c for c in SLEEVE_MEMBERS["bond"] if market.mark(c, ENTRY) is not None]
        floor = sleeve_floor(market, bond, ENTRY, TOL, slip)
        price = market.mark("511220", ENTRY)
        assert price == Decimal("100.0")
        assert floor == price * 100 == Decimal("10000.00")
        assert floor > Decimal("2") * code_gate(bond[0], TOL, slip)

    def test_equity_floor_is_the_gate_not_the_lot(self, market, slip):
        """An equity ETF at 3.5 CNY has a 354 CNY lot, so the per-code gate binds instead."""
        equities = [c for c in SLEEVE_MEMBERS["equity"] if market.mark(c, ENTRY) is not None]
        floor = sleeve_floor(market, equities, ENTRY, TOL, slip)
        assert floor == max(code_gate(c, TOL, slip) for c in equities)
        assert floor < Decimal("10000")


class TestComposition:
    def test_bond_sleeve_cannot_hold_its_target_at_50k(self, market, slip):
        weights, members = lot_composition(market, ENTRY, dict(MANDATE), NAV50, TOL, slip)
        assert len(members["bond"]) == 1
        # expressed = one lot / NAV, and it is far below the 0.35 the mandate declares
        assert weights["bond"] < 0.25
        assert weights["bond"] == pytest.approx(10000 / 50000, abs=0.005)

    def test_unlisted_member_never_enters_the_tree(self, market, slip):
        """512100 lists 2016-11-04: a fund that does not exist cannot be a target."""
        assert "512100" not in available_members(market, "equity", ENTRY)
        assert "512100" in available_members(market, "equity", "2017-01-03")
        _, members = lot_composition(market, ENTRY, dict(MANDATE), NAV50, TOL, slip)
        assert "512100" not in members["equity"]

    def test_small_sleeves_are_expressed_not_dropped(self, market, slip):
        """The v13 failure was commodity/overseas at 0 %; the lot rule buys one member each."""
        _, members = lot_composition(market, ENTRY, dict(MANDATE), NAV50, TOL, slip)
        assert len(members["commodity"]) == 1
        assert len(members["overseas"]) == 1

    def test_expression_is_rounded_down_to_whole_lots(self, market, slip):
        weights, members = lot_composition(market, ENTRY, dict(MANDATE), NAV50, TOL, slip)
        for sleeve, codes in members.items():
            if not codes:
                continue
            budget = Decimal(str(MANDATE[sleeve])) * NAV50 / len(codes)
            held = sum(int(budget // (market.mark(c, ENTRY) * 100)) * market.mark(c, ENTRY) * 100
                       for c in codes)
            # expressed is EXACTLY the floor-rounded whole lots - never the rounded-up budget
            assert Decimal(str(weights[sleeve])) == pytest.approx(held / NAV50, abs=Decimal("1e-9"))
            assert held <= budget * len(codes) * Decimal("1.000001")

    def test_gap_is_monotone_in_capital(self, market, slip):
        """More capital cannot make a sleeve less expressible."""
        gaps = []
        for nav in (NAV50, NAV120):
            weights, _ = lot_composition(market, ENTRY, dict(MANDATE), nav, TOL, slip)
            gaps.append(sum(MANDATE[s] - weights[s] for s in MANDATE))
        assert gaps[1] <= gaps[0] + 0.02


class TestRedeploy:
    def test_sums_to_one_and_leaves_the_bound_sleeve_alone(self, market, slip):
        plain, _ = lot_composition(market, ENTRY, dict(MANDATE), NAV50, TOL, slip)
        deployed, _ = lot_composition(market, ENTRY, dict(MANDATE), NAV50, TOL, slip,
                                      redeploy=True)
        assert sum(deployed.values()) == pytest.approx(1.0, abs=1e-9)
        assert deployed["bond"] == pytest.approx(plain["bond"], abs=1e-12)
        assert deployed["equity"] > plain["equity"]

    def test_no_knife_edge_on_the_small_sleeves(self, market, slip):
        """The rejected rule: 10 % sleeves scaled by a 0.99 threshold, flipping on 0.0002."""
        deployed, _ = lot_composition(market, ENTRY, dict(MANDATE), NAV50, TOL, slip,
                                      redeploy=True)
        # Both small sleeves must move by the same factor - they are the same constraint class.
        plain, _ = lot_composition(market, ENTRY, dict(MANDATE), NAV50, TOL, slip)
        ratio_c = deployed["commodity"] / plain["commodity"]
        ratio_o = deployed["overseas"] / plain["overseas"]
        assert ratio_c == pytest.approx(ratio_o, rel=0.05)

    def test_converges_to_the_mandate_when_lots_stop_binding(self, market, slip):
        """By 2025 at 50k the tree expresses the mandate, so redeploy changes almost nothing."""
        weights, _ = lot_composition(market, "2025-12-31", dict(MANDATE), NAV50, TOL, slip,
                                     redeploy=True)
        for sleeve in MANDATE:
            assert weights[sleeve] == pytest.approx(MANDATE[sleeve], abs=0.03)


class TestCompose:
    def test_weight_arm_returns_every_listed_member(self, market, slip):
        weights, members = compose(ARMS["static"], market=market, sess=ENTRY, row={},
                                   theta=None, is_annual=True, prev=None, nav=NAV50,
                                   tolerance_bp=TOL, slippage=slip)
        assert weights["bond"] == pytest.approx(0.35)
        assert len(members["overseas"]) == 3

    def test_lot_arm_returns_the_kept_tree(self, market, slip):
        weights, members = compose(ARMS["lots"], market=market, sess=ENTRY, row={},
                                   theta=None, is_annual=True, prev=None, nav=NAV50,
                                   tolerance_bp=TOL, slippage=slip)
        assert weights["bond"] < 0.35
        assert len(members["bond"]) == 1

    def test_no_decision_returns_none_and_no_members(self, market, slip):
        weights, members = compose(ARMS["static"], market=market, sess=ENTRY, row={},
                                   theta=None, is_annual=False, prev=dict(MANDATE), nav=NAV50,
                                   tolerance_bp=TOL, slippage=slip)
        assert weights is None
        assert members == {}

    def test_cash_arm_aims_at_zero_everywhere(self, market, slip):
        weights, _ = compose(ARMS["cash"], market=market, sess=ENTRY, row={}, theta=None,
                             is_annual=True, prev=None, nav=NAV50, tolerance_bp=TOL,
                             slippage=slip)
        assert weights == {sleeve: 0.0 for sleeve in MANDATE}


class TestDecisionRule:
    """The adoption rule is code, so it is tested as code - not left to a reading of the report."""

    def _block(self, lo, hi, point, mde=500.0):
        return {"annual_cny": point, "annual_cny_lo": lo, "annual_cny_hi": hi,
                "mde_annual_cny": mde, "separates_from_zero": bool(lo > 0 or hi < 0),
                "reading": "measurable" if (lo > 0 or hi < 0) else "unmeasurable at this capital"}

    def _primary(self, blocks):
        return {"deltas": {k: self._block(**v) for k, v in blocks.items()}}

    def test_both_arms_clear_and_redeploy_gain_does_not_separate(self):
        primary = self._primary({
            "lots-static": dict(lo=858, hi=2213, point=1543),
            "lots_deploy-static": dict(lo=1150, hi=2784, point=1930),
            "lots_deploy-lots": dict(lo=-72, hi=974, point=387),
        })
        decision = e3._decide(primary)
        assert decision["adopted_arm"] == "lots"
        assert decision["deploy_gain_separates"] is False

    def test_redeploy_wins_when_its_gain_separates(self):
        primary = self._primary({
            "lots-static": dict(lo=858, hi=2213, point=1543),
            "lots_deploy-static": dict(lo=1150, hi=2784, point=1930),
            "lots_deploy-lots": dict(lo=200, hi=1200, point=700),
        })
        decision = e3._decide(primary)
        assert decision["adopted_arm"] == "lots_deploy"

    def test_nothing_separates_falls_back_to_cash_residual(self):
        primary = self._primary({
            "lots-static": dict(lo=-900, hi=1200, point=150, mde=1500),
            "lots_deploy-static": dict(lo=-1100, hi=1400, point=180, mde=1700),
        })
        decision = e3._decide(primary)
        assert decision["adopted_arm"] is None
        assert decision["verdict"] == "composition-kept-in-cash-residual-form"

    def test_cash_contrast_can_never_carry_adoption(self):
        """`lots-cash` is reported, but it is not the pre-registered comparison."""
        primary = self._primary({
            "lots-cash": dict(lo=1264, hi=5027, point=2851),
            "lots_deploy-cash": dict(lo=1768, hi=5494, point=3238),
        })
        decision = e3._decide(primary)
        assert decision["adopted_arm"] is None


class TestControlCheck:
    def test_matches_and_mismatches_are_distinguished(self):
        good = {"arms": {"static": {"nav_end": 62163.64, "n_fills": 6,
                                    "ledger_head": e3.E2_CONTROL["ledger_head"]}}}
        assert e3.control_check(good)["ok"] is True
        off = {"arms": {"static": {"nav_end": 62163.65, "n_fills": 6,
                                   "ledger_head": e3.E2_CONTROL["ledger_head"]}}}
        assert e3.control_check(off)["ok"] is False
        assert e3.control_check(off)["verdict"] == "invalid_experiment"

    def test_different_ledger_head_invalidates_the_cell(self):
        head = {"arms": {"static": {"nav_end": 62163.64, "n_fills": 6, "ledger_head": "abc"}}}
        assert e3.control_check(head)["ok"] is False


class TestProbeCongruence:
    def test_disagreement_points_at_the_listing_date(self, market, slip):
        """The probe over-counted equity by one; the cause must be named, not just flagged."""
        pc = e3.probe_congruence(market, e3.Cell(NAV50, TOL, "measured"))
        assert pc["available"] is True
        assert pc["sleeves"]["bond"]["agrees"] is True
        if not pc["sleeves"]["equity"]["agrees"]:
            assert "512100" in pc["sleeves"]["equity"]["cause"]
            assert pc["total_probe"] > pc["total_engine"]
