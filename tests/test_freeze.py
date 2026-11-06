"""The L0 layer must be reproducible and must refuse a tampered artefact."""

import json
import shutil
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from newquant.data.freeze import build, canonical_hash, load
from newquant.eval.feasibility import executable_cells, lot_ladder, threshold_table

ROOT = Path(__file__).resolve().parents[1]
BARS = ROOT / "data" / "etf_bars.parquet"
FETCH_MANIFEST = ROOT / "data" / "etf_bars.manifest.json"

pytestmark = pytest.mark.skipif(
    not (BARS.exists() and FETCH_MANIFEST.exists()),
    reason="frozen bar file not present",
)


@pytest.fixture(scope="module")
def frozen(tmp_path_factory):
    out = tmp_path_factory.mktemp("frozen")
    manifest = build(BARS, FETCH_MANIFEST, out)
    return out, manifest


class TestFreeze:
    def test_build_is_idempotent_and_hashes_the_same_table(self, frozen):
        out, first = frozen
        second = build(BARS, FETCH_MANIFEST, out)
        assert second["venue_hash"] == first["venue_hash"]
        assert second["previous_venue_hash"] == first["venue_hash"]
        assert second["changed"] is False

    def test_reload_verifies_the_hash(self, frozen):
        out, manifest = frozen
        venue, loaded = load(out)
        assert loaded["venue_hash"] == manifest["venue_hash"]
        assert len(venue) == 15
        assert venue["code"].is_unique

    def test_a_tampered_table_refuses_to_load(self, frozen, tmp_path):
        out, _ = frozen
        shutil.copy(out / "venue.parquet", tmp_path / "venue.parquet")
        shutil.copy(out / "venue.manifest.json", tmp_path / "venue.manifest.json")
        venue = pd.read_parquet(tmp_path / "venue.parquet")
        venue.loc[0, "lot_notional"] += 1.0
        venue.to_parquet(tmp_path / "venue.parquet", index=False)
        with pytest.raises(RuntimeError, match="does not match its manifest hash"):
            load(tmp_path)

    def test_coarse_lot_names_are_flagged_untradable(self, frozen):
        out, _ = frozen
        venue, _ = load(out)
        coarse = set(venue.loc[~venue["tradable"], "code"])
        assert coarse == {"511010", "511260", "511880", "511990"}
        tradable = venue[venue["tradable"]]
        assert len(tradable) == 11
        for nav in (50_000, 75_000, 100_000):
            assert (tradable["lot_notional"] / nav).max() <= 0.10

    def test_gap_days_are_counted_not_patched(self, frozen):
        out, _ = frozen
        venue, _ = load(out)
        gaps = dict(zip(venue["code"], venue["gap_days"]))
        assert gaps["511220"] == 6
        assert gaps["510300"] == 0

    def test_manifest_pins_the_source_file(self, frozen):
        _, manifest = frozen
        assert manifest["source"]["bars_rows"] == 45197
        assert len(manifest["source"]["bars_sha256"]) == 64
        assert manifest["checks"]["all_codes_mapped"] is True


class TestFeasibility:
    def test_thresholds_are_ordered_and_floor_exists(self):
        t = threshold_table().dropna(subset=["min_order_cny"])
        per_tol = t.groupby("tolerance_bp")["min_order_cny"].first().astype(float)
        assert per_tol["7.6"] == 20_000
        assert per_tol["10"] > per_tol["15.1"] > per_tol["30"] > per_tol["50"]

    def test_ten_bp_is_outside_budget_below_hundred_thousand(self):
        t = threshold_table()
        row = t[(t["tolerance_bp"] == "10") & (t["nav"] == 75_000)].iloc[0]
        assert bool(row["within_monthly_sleeve_budget"]) is False
        row = t[(t["tolerance_bp"] == "15.1") & (t["nav"] == 75_000)].iloc[0]
        assert bool(row["within_monthly_sleeve_budget"]) is True

    def test_ladder_finds_the_first_clearing_lot_count(self):
        lad = lot_ladder(Decimal("16.00"), 75_000, Decimal("15.1"))
        assert lad["min_lots"] == 4
        assert lad["notional"] == "6400.00"
        assert lad["bp"] == "12.91"
        assert [f["lots"] for f in lad["failing_lots"]] == [1, 2, 3]

    def test_executable_cells_counts_only_gate_clearing_orders(self):
        venue = pd.DataFrame([{"code": "510300", "tradable": True}])
        bars = pd.DataFrame(
            {"code": ["510300"] * 3, "date": ["2020-01-31", "2020-02-28", "2020-03-31"],
             "close": [16.0, 16.0, 16.0]})
        cells = executable_cells(bars, venue, Decimal("15.1"), Decimal("0.10"))
        assert cells["nav"].nunique() == 3
        # 10% of 50k = 5000 -> 3 lots = 4800 (fails); 10% of 75k = 7500 -> 4 lots = 6400 (passes)
        at_50k = cells[cells["nav"] == 50_000]
        at_75k = cells[cells["nav"] == 75_000]
        assert not at_50k["executable"].any()
        assert at_75k["executable"].all()
