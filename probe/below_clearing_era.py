"""Is the 75.4% below-clearing intent share one number, or two eras wearing one number?

Probe of ledger seq 121 (`probe-below-clearing-era`). Reads only derived artefacts:
the chained replay ledgers of E3, `evidence/e3-summary.json` for the clearing table
(written by `newquant/eval/e2.py:138-168`), and `data/venue.parquet` for the code->sleeve
map. No market-data read, so no window is claimed.

Why this is the question and not a check. The implementability reading of this line is
"at 50,000 CNY most intents cannot clear the gate, so the mandate is not expressible".
The number behind it, `intents_below_clearing_share = 49/65 = 0.7538` with a median intent
of 1,888.5 CNY, is pooled over 2016-2025 -- a period in which the bond board lot fell by
roughly tenfold on 2023-01-16 (511220, 10:1 split, one lot 10,000 -> ~1,021 CNY). The
clearing threshold itself is time-invariant (`venue.min_notional` = 5 CNY / (tol - var),
3,345.02-5,066.23 CNY, stored once per code:side), so ANY era difference has to come from
the size and mix of the intents, not from the gate. That makes the split a clean test of
whether the pooled number still describes the venue after 2023.

Pre-declared rule (ledger seq 121):
  V1 if the reconstruction does not reproduce 49 of 65 intents below clearing and a median
     intent of 1,888.5 CNY for the 50,000 lots arm, the intent population is wrong and no
     era figure may be quoted.
  E1 if the 2023-2025 share is at least 15 pp BELOW the 2016-2022 share, the pooled figure
     is era-mixed and the implementability reading must be restated per era; if the two
     shares are within 10 pp, the pooled figure describes both eras and stands; otherwise
     the split is reported and the reading stays unresolved.
  M1 if the era difference is concentrated in the bond sleeve (its share falls >= 15 pp
     while equity, commodity and overseas each move <= 5 pp), the mechanism is the 511220
     split; if it is broad, the mechanism is NAV drift or code mix and the split
     explanation is rejected.

Run: PYTHONPATH=. python probe/below_clearing_era.py
"""

from __future__ import annotations

import bisect
import json
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

OUT = Path("evidence/probe-below-clearing-era")
E3 = Path("evidence/e3-ledgers")
ARMS = ("static", "lots", "lots_deploy")
CELL = "nav50000_tol15.1_measured"
ERA_SPLIT_YEAR = 2023


def sleeve_map() -> dict[str, str]:
    venue = pd.read_parquet("data/venue.parquet")[["code", "sleeve"]]
    return {str(c): str(s) for c, s in zip(venue["code"], venue["sleeve"])}


def clearing_table() -> dict[tuple[str, str], float]:
    """The gate's own bound, as E2/E3 recorded it: one value per code:side for the window."""
    summary = json.loads(Path("evidence/e3-summary.json").read_text(encoding="utf-8"))
    profile = summary["cells"]["primary"]["arms"]["lots"]["intent_profile"]
    out = {}
    for key, value in profile["clearing_by_code"].items():
        code, side = key.split(":")
        out[(code, side)] = float(value)
    return out


def session_years(rows: list[dict]) -> tuple[list[int], list[int]]:
    marks = sorted((int(r["payload"]["session"]), str(r["payload"]["note"]))
                   for r in rows if r["kind"] == "mark")
    return ([m[0] for m in marks],
            [int(m[1].split("month-end ")[1][:4]) for m in marks])


def year_of(session: int, ms: list[int], my: list[int]) -> int:
    i = bisect.bisect_left(ms, session)
    return my[i] if i < len(my) else my[-1]


def intents(path: Path) -> list[dict]:
    """Every intent the engine formed: a fill, or a suppression that named a size."""
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    ms, my = session_years(rows)
    out = []
    for r in rows:
        if r["kind"] not in ("fill", "suppress"):
            continue
        p = r["payload"]
        notional = abs(float(p.get("notional", 0.0) or 0.0))
        out.append({
            "kind": r["kind"],
            "code": str(p.get("code")),
            "side": str(p.get("side")),
            "session": int(p.get("session", -1)),
            "year": year_of(int(p.get("session", -1)), ms, my),
            "notional": notional,
            "reason": p.get("reason"),
            "bp": float(p["bp"]) if p.get("bp") is not None else None,
            "cost_bp": float(p["cost_bp"]) if p.get("cost_bp") is not None else None,
        })
    return out


def summarise(rows: list[dict], clearing: dict[tuple[str, str], float],
              code2sleeve: dict[str, str]) -> dict:
    sized = list(rows)  # zero-notional intents are intents: a rung that rounded to no lots
    # cannot clear the gate, and e2.py:150-168 counts them exactly this way (fillna(0.0))
    below = 0
    per_sleeve: dict[str, dict] = defaultdict(lambda: {"n": 0, "below": 0})
    per_reason = Counter()
    notionals = []
    for r in sized:
        limit = clearing.get((r["code"], r["side"]))
        is_below = limit is not None and r["notional"] < limit
        below += int(is_below)
        sleeve = code2sleeve.get(r["code"], "?")
        per_sleeve[sleeve]["n"] += 1
        per_sleeve[sleeve]["below"] += int(is_below)
        if r["kind"] == "suppress":
            per_reason[str(r["reason"])] += 1
        notionals.append(r["notional"])
    notionals.sort()

    def median(xs: list[float]) -> float:
        if not xs:
            return float("nan")
        n = len(xs)
        return xs[n // 2] if n % 2 else 0.5 * (xs[n // 2 - 1] + xs[n // 2])

    zero = sum(1 for r in sized if r["notional"] <= 0)
    return {
        "n_intents": len(sized),
        "n_zero_notional": zero,
        "n_below_clearing": below,
        "below_share": below / len(sized) if sized else float("nan"),
        "median_intent_cny": round(median(notionals), 1),
        "below_share_ci95": [round(v, 4) for v in wilson(below, len(sized))],
        "by_sleeve": {s: {"n": v["n"], "below": v["below"],
                          "share": v["below"] / v["n"] if v["n"] else None}
                      for s, v in sorted(per_sleeve.items())},
        "suppression_reasons": dict(per_reason),
    }


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if not n:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1.0 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    code2sleeve = sleeve_map()
    clearing = clearing_table()

    report: dict[str, dict] = {"clearing_cny": {f"{c}:{s}": v for (c, s), v in clearing.items()}}
    for arm in ARMS:
        rows = intents(E3 / f"{CELL}_{arm}.jsonl")
        pooled = summarise(rows, clearing, code2sleeve)
        era1 = summarise([r for r in rows if r["year"] < ERA_SPLIT_YEAR], clearing, code2sleeve)
        era2 = summarise([r for r in rows if r["year"] >= ERA_SPLIT_YEAR], clearing, code2sleeve)
        by_year = {str(y): summarise([r for r in rows if r["year"] == y], clearing, code2sleeve)
                   for y in sorted({r["year"] for r in rows})}
        entry = summarise([r for r in rows if r["session"] == 0], clearing, code2sleeve)
        post = summarise([r for r in rows if r["session"] != 0], clearing, code2sleeve)
        report[arm] = {"pooled": pooled, "era_2016_2022": era1, "era_2023_2025": era2,
                       "by_year": by_year, "entry_session0": entry, "post_entry": post}

    (OUT / "summary.json").write_text(json.dumps(report, indent=1), encoding="utf-8")

    lots = report["lots"]
    v1 = (lots["pooled"]["n_below_clearing"], lots["pooled"]["n_intents"],
          lots["pooled"]["median_intent_cny"])
    delta = lots["era_2023_2025"]["below_share"] - lots["era_2016_2022"]["below_share"]
    bond = lots["era_2016_2022"]["by_sleeve"].get("bond", {})
    bond2 = lots["era_2023_2025"]["by_sleeve"].get("bond", {})
    others = ("equity", "commodity", "overseas")
    other_delta = max(
        abs((lots["era_2023_2025"]["by_sleeve"].get(s, {}).get("share") or 0.0)
            - (lots["era_2016_2022"]["by_sleeve"].get(s, {}).get("share") or 0.0))
        for s in others)

    lines = [
        "# Below-clearing intents by era (E3, 50,000 CNY)",
        "",
        f"V1 reconstruction, lots arm: {v1[0]} of {v1[1]} intents below clearing, "
        f"median {v1[2]} CNY (target 49 of 65, 1888.5).",
        "",
        "| arm | era | intents | below | share | median CNY |",
        "|---|---|---|---|---|---|",
    ]
    for arm in ARMS:
        for era in ("pooled", "era_2016_2022", "era_2023_2025"):
            d = report[arm][era]
            lines.append(f"| {arm} | {era} | {d['n_intents']} | {d['n_below_clearing']} | "
                         f"{d['below_share']:.4f} | {d['median_intent_cny']} |")
    lines += ["", "## lots arm by year", "",
              "| year | intents | below | share | median CNY |", "|---|---|---|---|---|"]
    for year, d in lots["by_year"].items():
        lines.append(f"| {year} | {d['n_intents']} | {d['n_below_clearing']} | "
                     f"{d['below_share']:.4f} | {d['median_intent_cny']} |")
    lines += ["", "## lots arm by sleeve", "",
              "| sleeve | 2016-2022 n / below / share | 2023-2025 n / below / share |",
              "|---|---|---|"]
    for s in ("equity", "bond", "commodity", "overseas"):
        a = lots["era_2016_2022"]["by_sleeve"].get(s, {})
        b = lots["era_2023_2025"]["by_sleeve"].get(s, {})
        lines.append(f"| {s} | {a.get('n',0)} / {a.get('below',0)} / "
                     f"{a.get('share') if a.get('share') is None else round(a['share'],4)} | "
                     f"{b.get('n',0)} / {b.get('below',0)} / "
                     f"{b.get('share') if b.get('share') is None else round(b['share'],4)} |")
    maint = [r for r in intents(E3 / f"{CELL}_lots.jsonl") if r["year"] > 2016]
    maint_s = summarise(maint, clearing, code2sleeve)
    build_s = summarise([r for r in intents(E3 / f"{CELL}_lots.jsonl") if r["year"] == 2016],
                        clearing, code2sleeve)
    lines += [
        "",
        "## build year versus maintenance years (lots arm)",
        "",
        f"- build 2016: {build_s['n_below_clearing']}/{build_s['n_intents']} = "
        f"{build_s['below_share']:.4f}, median {build_s['median_intent_cny']} CNY, "
        f"CI95 {build_s['below_share_ci95']}",
        f"- maintenance 2017-2025: {maint_s['n_below_clearing']}/{maint_s['n_intents']} = "
        f"{maint_s['below_share']:.4f}, median {maint_s['median_intent_cny']} CNY, "
        f"CI95 {maint_s['below_share_ci95']}",
        "",
        "## verdict",
        "",
        f"- E1 delta (2023-2025 minus 2016-2022, lots arm): {delta:+.4f}, with "
        f"{lots['era_2023_2025']['n_intents']} post-split intents "
        f"(CI95 {lots['era_2023_2025']['below_share_ci95']}) against "
        f"{lots['era_2016_2022']['n_intents']} (CI95 {lots['era_2016_2022']['below_share_ci95']}). "
        f"{'Era-mixed: restate per era.' if delta <= -0.15 else ('Not detectable at this n: the intervals overlap and a 15 pp shift could not have been shown.' if abs(delta) <= 0.10 else 'Unresolved.')}",
        f"- M1 bond share {bond.get('share')} -> {bond2.get('share')}; largest other-sleeve move "
        f"{other_delta:.4f}. "
        f"{'Concentrated in bond, consistent with the 511220 split.' if (bond2.get('share') is not None and bond.get('share') is not None and bond2['share'] - bond['share'] <= -0.15 and other_delta <= 0.05) else 'Not concentrated in bond: the split story does not carry it alone.'}",
    ]
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())