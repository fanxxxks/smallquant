"""`kind="hold"` — the arm every kill criterion about "just buy it and stop" needed and lacked.

Two properties, both structural rather than numeric:

(a) the rule submits the mandate *only* on the entry decision, so a January month-end with a
    book already on it returns ``None`` even though ``static`` returns the mandate there;
(b) in a replay, every fill of a hold arm falls on the entry session, and its entry fills are
    the same rows ``static`` produces on that session — i.e. hold really is "static minus the
    annual re-submission", not a different entry composition.

A one-year window keeps the test cheap; the property does not depend on window length. Nothing
here asserts a return, so a venue or price update cannot make it fail for the wrong reason.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from newquant.replay import (ARMS, MANDATE, Arm, build_market, replay, slippage_table,
                            target_weights)

NAV = Decimal("50000")
TOL = Decimal("15.1")
START, END = "2020-01-02", "2020-12-31"
HOLD_ARMS = ("hold", "hold_lot", "hold_deploy")


@pytest.fixture(scope="module")
def market():
    return build_market("data/etf_bars.parquet", "data/corp_actions.parquet",
                        "evidence/sleeve_scores.parquet", start=START, end=END)


@pytest.fixture(scope="module")
def results(market, tmp_path_factory):
    out = {}
    ledger_dir = tmp_path_factory.mktemp("hold-ledgers")
    for name in HOLD_ARMS + ("static",):
        out[name] = replay(
            market,
            ARMS[name],
            nav0=NAV,
            tolerance_bp=TOL,
            cost_mode="measured",
            ledger_path=ledger_dir / f"{name}.jsonl",
            start=START,
            end=END,
        )
    return out


class TestRule:
    def test_hold_submits_once_and_never_again(self):
        arm = ARMS["hold"]
        assert target_weights(arm, row={}, theta=None, is_annual=True, prev=None) == dict(MANDATE)
        for prev in ({s: 0.25 for s in MANDATE}, dict(MANDATE)):
            for is_annual in (True, False):
                assert target_weights(arm, row={}, theta=None, is_annual=is_annual,
                                      prev=prev) is None

    def test_static_does_resubmit_so_the_contrast_is_real(self):
        """The control this arm is differenced against must still re-submit every January."""
        arm = ARMS["static"]
        assert target_weights(arm, row={}, theta=None, is_annual=True,
                              prev={s: 0.25 for s in MANDATE}) == dict(MANDATE)
        assert target_weights(arm, row={}, theta=None, is_annual=False,
                              prev={s: 0.25 for s in MANDATE}) is None

    def test_lot_variants_keep_their_entry_composition(self):
        """The two lot variants differ from `hold` only at entry, not in when they submit."""
        for name in ("hold_lot", "hold_deploy"):
            arm = ARMS[name]
            assert arm.kind == "hold" and arm.lot_defined
            assert arm.redeploy is (name == "hold_deploy")

    def test_unknown_kind_still_raises(self):
        with pytest.raises(ValueError):
            target_weights(Arm("x", "nope", False), row={}, theta=None, is_annual=False, prev=None)


class TestReplay:
    def test_every_hold_fill_is_on_the_entry_session(self, results, market):
        entry = market.sessions[0]
        for name in HOLD_ARMS:
            fills = results[name].fills
            assert len(fills) > 0, f"{name} never bought the book"
            late = fills[fills["date"] != entry]
            assert len(late) == 0, f"{name} traded after entry:\n{late}"

    def test_entry_fills_match_static_row_for_row(self, results, market):
        """Same entry composition means the same rows — the only difference is the calendar."""
        entry = market.sessions[0]
        static = results["static"].fills
        base = static[static["date"] == entry].reset_index(drop=True)
        assert len(base) > 0
        for name in HOLD_ARMS[:1]:  # `hold` uses `static`'s entry path exactly
            held = results[name].fills
            held = held[held["date"] == entry].reset_index(drop=True)
            assert list(held["code"]) == list(base["code"])
            assert list(held["lots"]) == list(base["lots"])
            assert list(held["notional"]) == list(base["notional"])

    def test_hold_forms_no_intent_after_entry(self, results, market):
        """No suppression dated after entry either: the arm does not even form an intent then.

        The entry session's own intents *can* be refused — a 2020-01-02 slice of 40-90 codes'
        worth of NAV sits under the gate — so the assertion is about dates, not about zero.
        """
        entry = market.sessions[0]
        for name in HOLD_ARMS:
            supp = results[name].suppressions
            late = supp[supp["date"] != entry] if len(supp) else supp
            assert len(late) == 0, f"{name} formed intents after entry:\n{late}"