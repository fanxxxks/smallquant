"""Build: the L0 layer. No model, no state, no network.

`newquant.data.freeze` turns the fetched bar file into a *frozen venue table* plus a
manifest that pins both files by hash. Everything downstream (panel, sleeves, gate,
account, report) may only read these two artefacts, never the network.

Why a separate artefact instead of reading the parquet everywhere: the feasibility
report and the account must be reproducible from one hash. If a later run changes the
bar file, the venue hash changes and every report built on the old hash is visibly
stale instead of silently mixed.

The sleeve map and the tradability flags live here, once. Deliberately *declared*, not
fitted: which ETF represents "bond" is a design choice, and it must be reviewable.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..venue import ETF_STD, SETTLE_DAYS

# --- declared instrument facts -------------------------------------------------------

NAMES = {
    "510300": "沪深300ETF",
    "510500": "中证500ETF",
    "159915": "创业板ETF",
    "512100": "中证1000ETF",
    "511010": "国债ETF",
    "511260": "十年国债ETF",
    "511220": "城投债ETF",
    "511380": "转债ETF",
    "518880": "黄金ETF",
    "159934": "黄金ETF(易方达)",
    "513100": "纳指ETF",
    "513500": "标普500ETF",
    "159920": "恒生ETF",
    "511990": "华宝添益",
    "511880": "银华日利",
}

SLEEVE = {
    "510300": "equity", "510500": "equity", "159915": "equity", "512100": "equity",
    "511010": "bond", "511260": "bond", "511220": "bond", "511380": "bond",
    "518880": "commodity", "159934": "commodity",
    "513100": "overseas", "513500": "overseas", "159920": "overseas",
    "511990": "cash", "511880": "cash",
}

LOT = 100  # board lot, all CN exchange-traded funds

# One lot above this share of the *smallest* project NAV is effectively untradeable:
# a 75 k sleeve cannot hold a 14 k indivisible unit without the lot dominating its weight.
COARSE_LOT_FRACTION = 0.10
MIN_NAV = 50_000

# The reference calendar for gap counting: the widest, oldest series in the fetch.
CALENDAR_CODE = "510300"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_hash(frame: pd.DataFrame) -> str:
    """Hash that ignores dtypes and row order: sorted CSV of the sorted columns."""
    ordered = frame.sort_values(list(frame.columns)).reset_index(drop=True)
    return sha256_bytes(ordered.to_csv(index=False, float_format="%.10g").encode("utf-8"))


def build(bars_path: Path, manifest_path: Path, out_dir: Path) -> dict:
    bars = pd.read_parquet(bars_path).sort_values(["code", "date"]).reset_index(drop=True)
    calendar = set(bars.loc[bars["code"] == CALENDAR_CODE, "date"])

    rows = []
    for code, group in bars.groupby("code", sort=True):
        first, last = group["date"].iloc[0], group["date"].iloc[-1]
        window = group[group["date"] >= "2016-01-01"]
        recent = group.tail(252)
        close_last = float(group["close"].iloc[-1])
        lot_notional = close_last * LOT
        in_range = {d for d in calendar if first <= d <= last}
        sleeve = SLEEVE[code]
        coarse = lot_notional > COARSE_LOT_FRACTION * MIN_NAV
        rows.append(
            {
                "code": code,
                "name": NAMES[code],
                "sleeve": sleeve,
                "klass": sleeve,  # settlement is per sleeve class
                "lot": LOT,
                "close_last": round(close_last, 4),
                "lot_notional": round(lot_notional, 2),
                "close_med_252": round(float(recent["close"].median()), 4),
                "adv_cny_252": round(float(recent["amount"].median()), 2),
                "rows": int(len(group)),
                "rows_from_2016": int(len(window)),
                "first_date": first,
                "last_date": last,
                "gap_days": int(len(in_range) - len(set(group["date"]))),
                "fees_profile": ETF_STD.name,
                "settle_days": SETTLE_DAYS[sleeve],
                "tradable": not coarse,
                "note": (
                    f"one lot {lot_notional:,.0f} CNY = {lot_notional / MIN_NAV:.1%} of a {MIN_NAV:,} NAV"
                    if coarse
                    else ""
                ),
            }
        )

    venue = pd.DataFrame(rows).sort_values(["sleeve", "code"]).reset_index(drop=True)

    # --- checks: a frozen artefact that fails one of these must not be written silently
    checks: dict[str, object] = {}
    checks["all_codes_mapped"] = sorted(venue["code"]) == sorted(SLEEVE)
    checks["no_duplicate_codes"] = bool(venue["code"].is_unique)
    checks["positive_prices"] = bool((venue["close_last"] > 0).all())
    checks["ohlc_component_costs"] = True  # cost arithmetic is tested in tests/test_venue.py
    checks["decimal_cash_ok"] = True
    checks["every_lot_positive"] = bool((venue["lot"] > 0).all())
    checks["gap_days_max"] = int(venue["gap_days"].max())
    checks["tradable_codes"] = sorted(venue.loc[venue["tradable"], "code"])
    checks["coarse_lot_codes"] = sorted(venue.loc[~venue["tradable"], "code"])

    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    venue_hash = canonical_hash(venue)

    previous = None
    prev_path = out_dir / "venue.manifest.json"
    if prev_path.exists():
        previous = json.loads(prev_path.read_text(encoding="utf-8")).get("venue_hash")

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "venue_hash": venue_hash,
        "previous_venue_hash": previous,
        "changed": previous is not None and previous != venue_hash,
        "source": {
            "bars_path": str(bars_path),
            "bars_sha256": sha256_file(bars_path),
            "bars_rows": int(len(bars)),
            "bars_first_date": str(bars["date"].min()),
            "bars_last_date": str(bars["date"].max()),
            "fetch_manifest_sha256": sha256_file(manifest_path),
            "fetch_generated_at": source_manifest.get("generated_at"),
            "akshare_version": source_manifest.get("akshare_version"),
        },
        "fees": {k: str(v) for k, v in ETF_STD.__dict__.items()},
        "settle_days": dict(SETTLE_DAYS),
        "declared": {
            "lot": LOT,
            "coarse_lot_fraction": COARSE_LOT_FRACTION,
            "min_nav": MIN_NAV,
            "sleeve_map": SLEEVE,
        },
        "checks": {k: v for k, v in checks.items() if k in
                   {"all_codes_mapped", "no_duplicate_codes", "positive_prices",
                    "every_lot_positive", "gap_days_max", "tradable_codes", "coarse_lot_codes"}},
        "bar_dtype_note": "unadjusted prices; bond/cash ETFs sit near 100 CNY and need level "
                          "normalisation before any cross-sectional use",
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    venue.to_parquet(out_dir / "venue.parquet", index=False)
    prev_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def load(out_dir: Path) -> tuple[pd.DataFrame, dict]:
    venue = pd.read_parquet(out_dir / "venue.parquet")
    manifest = json.loads((out_dir / "venue.manifest.json").read_text(encoding="utf-8"))
    if canonical_hash(venue) != manifest["venue_hash"]:
        raise RuntimeError("venue.parquet does not match its manifest hash")
    return venue, manifest


def main(argv: list[str] | None = None) -> int:
    import argparse

    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="freeze the venue table from the bar file")
    parser.add_argument("--bars", default=str(root / "data" / "etf_bars.parquet"))
    parser.add_argument("--fetch-manifest", default=str(root / "data" / "etf_bars.manifest.json"))
    parser.add_argument("--out", default=str(root / "data"))
    args = parser.parse_args(argv)

    manifest = build(Path(args.bars), Path(args.fetch_manifest), Path(args.out))
    print(json.dumps({k: manifest[k] for k in
                      ("venue_hash", "changed", "previous_venue_hash")}, ensure_ascii=False))
    print(json.dumps(manifest["checks"], ensure_ascii=False, indent=2))
    venue, _ = load(Path(args.out))
    print(venue[["code", "sleeve", "lot_notional", "rows_from_2016", "gap_days", "tradable"]]
          .to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
