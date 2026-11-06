"""The conformance criteria as amended at seq 126, pinned where the artefacts cannot show them.

Two properties matter and neither was true of the retired fill-ratio check:

* a book that never trades must pass. Its ratio is ``None`` (no intents), which the old floor
  marked as a failure, so the most conformant book in the sample was judged the worst.
* a book that starts re-targeting must fail. The ceilings are twice the measured rate, so they
  are loose, but they are not vacuous: a rule that begins placing maintenance trades breaches
  both of them.

The ledgers here are synthetic and chained through the real ``LedgerStore``, so the reproduction
criterion (d) is exercised too - an edited or re-sequenced file raises rather than reading.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from newquant.ledger import LedgerStore
from newquant.replay import MANDATE, SLEEVE_MEMBERS
from probe.conformance_dryrun import FILLS_PER_YEAR_MAX, POST_TURNOVER_MAX, evaluate

CODES = {sleeve: members[0] for sleeve, members in SLEEVE_MEMBERS.items()}
MONTHS = 24


def write_ledger(path, *, fills=(), suppressions=0, marks=MONTHS) -> str:
    """A chained ledger with month-end marks, optional suppressions and the given fills.

    ``fills`` is a sequence of ``(sleeve, session, notional)``; session 0 is the build.
    """
    store = LedgerStore(path)
    for i in range(marks):
        year, month = 2020 + i // 12, i % 12 + 1
        store.append("mark", {"session": i * 21, "note": f"month-end {year}-{month:02d}-28"})
    for i in range(suppressions):
        store.append("suppress", {"code": CODES["equity"], "side": "buy", "reason": "below_cost_gate",
                                  "intended_lots": 1, "notional": "700.00", "session": 40 + i,
                                  "tolerance_bp": "15.1"})
    for sleeve, session, notional in fills:
        store.append("fill", {"code": CODES[sleeve], "side": "buy", "lots": 1, "notional": notional,
                              "session": session, "price": "1.000", "cost_bp": "6.0"})
    return LedgerStore(path).head


def build_case(tmp_path, *, arm_fills, control_fills=(), entry_cash=0.196,
               control_entry_cash=0.374, sleeves=None):
    """A summary/monthly pair shaped like the E3 artefacts, over two synthetic ledgers."""
    sleeves = sleeves or {s: w for s, w in MANDATE.items()}
    arm_path, control_path = tmp_path / "arm.jsonl", tmp_path / "control.jsonl"
    arm_head = write_ledger(arm_path, fills=arm_fills, suppressions=3)
    control_head = write_ledger(control_path, fills=control_fills)

    arm = {
        "cost_bp_of_nav_per_year": 1.0, "turnover_per_year": 0.1, "n_fills": len(arm_fills),
        "ledger_head": arm_head, "suppressed_by_reason": {"below_cost_gate": 3},
        "entry": {"entry_cash": entry_cash, "entry_codes": ["a"],
                  **{f"entry_{s}": w for s, w in sleeves.items()}},
    }
    control = {"cost_bp_of_nav_per_year": 1.0, "turnover_per_year": 0.1,
               "n_fills": len(control_fills), "ledger_head": control_head,
               "suppressed_by_reason": {}, "entry": {"entry_cash": control_entry_cash,
                                                     "entry_codes": ["a"],
                                                     **{f"entry_{s}": w for s, w in sleeves.items()}}}
    summary = {"cells": {"primary": {"cell": {"nav0": 50000.0},
                                     "arms": {"lots": arm, "static": control}}}}
    dates = pd.date_range("2020-01-31", periods=MONTHS, freq="ME").strftime("%Y-%m-%d")
    rows = [{"date": d, "arm": "lots", **{f"realised_{s}": w for s, w in sleeves.items()},
             **{f"members_{s}": 1 for s in sleeves}} for d in dates]
    monthly = pd.DataFrame(rows)
    return summary, monthly, {"lots": arm_path, "static": control_path}


def run_case(tmp_path, **kwargs):
    summary, monthly, paths = build_case(tmp_path, **kwargs)
    return evaluate(summary, monthly, paths, cell="primary", arm="lots", control_arm="static",
                    months_required=10)


class TestNeverTradingBook:
    def test_passes_every_criterion(self, tmp_path):
        """No fills at all: the case the retired ratio floor failed."""
        result = run_case(tmp_path, arm_fills=())
        assert result["failed"] == []
        assert result["checks"]["e_maintenance_rate"]["measured"]["post_entry_fills"] == 0
        assert result["reported"]["fill_ratio"]["equity"] == 0.0

    def test_ratio_is_absent_without_intents(self, tmp_path):
        """A book with neither fills nor suppressions has no ratio - reported, never gated."""
        summary, monthly, paths = build_case(tmp_path, arm_fills=())
        for name in paths:
            rows = [json.loads(line) for line in paths[name].read_text().splitlines() if line.strip()]
            paths[name].write_text("")  # rebuilt below without suppressions
            store = LedgerStore(paths[name])
            for rec in rows:
                if rec["kind"] != "suppress":
                    store.append(rec["kind"], rec["payload"])
        summary["cells"]["primary"]["arms"]["lots"]["n_fills"] = 0
        summary["cells"]["primary"]["arms"]["lots"]["ledger_head"] = LedgerStore(paths["lots"]).head
        summary["cells"]["primary"]["arms"]["lots"]["suppressed_by_reason"] = {}
        result = evaluate(summary, monthly, paths, cell="primary", arm="lots",
                          control_arm="static", months_required=10)
        assert result["reported"]["fill_ratio"]["equity"] is None
        assert result["checks"]["e_maintenance_rate"]["pass"] is True


class TestMaintenanceCeiling:
    def test_build_fills_are_not_maintenance(self, tmp_path):
        """Session 0 is the build: seven fills there add nothing to the maintenance rate."""
        result = run_case(tmp_path, arm_fills=[("equity", 0, 5000.0)] * 7)
        assert result["checks"]["e_maintenance_rate"]["pass"] is True
        assert result["checks"]["b_entry_composition"]["pass"] is True

    def test_churning_book_fails(self, tmp_path):
        """One maintenance fill a month over two years: 12 a year against a ceiling of 2."""
        monthly_sessions = list(range(1, MONTHS + 1))
        result = run_case(tmp_path, arm_fills=[("equity", s, 50_000.0) for s in monthly_sessions])
        check = result["checks"]["e_maintenance_rate"]
        assert check["pass"] is False
        assert check["measured"]["post_entry_fills_per_year"] == pytest.approx(12.0)
        assert check["measured"]["post_entry_turnover"] > POST_TURNOVER_MAX
        assert result["failed"] == ["e_maintenance_rate"]

    def test_one_fill_a_year_is_conformant(self, tmp_path):
        """The measured book: 9 fills in 9 years. One a year must not read as churn."""
        result = run_case(tmp_path, arm_fills=[("equity", 21 * i, 4000.0) for i in range(1, 3)])
        check = result["checks"]["e_maintenance_rate"]
        assert check["measured"]["post_entry_fills_per_year"] == pytest.approx(1.0)
        assert check["pass"] is True
        assert check["measured"]["post_entry_fills"] <= FILLS_PER_YEAR_MAX * 2


class TestEntryComposition:
    def test_dropped_sleeve_fails(self, tmp_path):
        """The v13 failure: commodity and overseas at 0 % of NAV."""
        sleeves = dict(MANDATE)
        sleeves["commodity"] = 0.0
        result = run_case(tmp_path, arm_fills=(), sleeves=sleeves)
        assert result["checks"]["b_entry_composition"]["pass"] is False
        assert result["checks"]["b_entry_composition"]["gaps_pp"]["commodity"] == pytest.approx(-10.0)

    def test_more_idle_cash_than_the_control_fails(self, tmp_path):
        result = run_case(tmp_path, arm_fills=(), entry_cash=0.40, control_entry_cash=0.37)
        assert result["checks"]["b_entry_composition"]["pass"] is False

    def test_less_idle_cash_than_the_control_passes(self, tmp_path):
        result = run_case(tmp_path, arm_fills=(), entry_cash=0.196, control_entry_cash=0.374)
        check = result["checks"]["b_entry_composition"]
        assert check["pass"] is True
        assert check["entry_cash"] < check["control_entry_cash"]


class TestRetiredCriteria:
    def test_no_cost_or_ratio_criterion_remains(self, tmp_path):
        """Both retired at seq 117 and seq 126: reported, never in the failed list."""
        result = run_case(tmp_path, arm_fills=[("equity", s, 50_000.0) for s in range(1, 13)])
        assert "b_cost_bp_per_year" not in result["checks"]
        assert "e_fill_ratio" not in result["checks"]
        assert "cost_bp_of_nav_per_year" in result["reported"]
        assert "fill_ratio" in result["reported"]