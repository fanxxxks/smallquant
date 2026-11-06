"""E1 — the one experiment that decides the prediction branch.

Pre-registered in `docs/direction-architecture.md` §6, before any result here existed. It
asks one question: does a small nonlinear model earn more than a ridge on the same panel
features, at the same horizon, after the same cost gate? Nothing about the arms is allowed
to differ except the functional form.

What this module produces and what it does not:

* it produces the pre-registered *secondary* numbers — per-arm rank IC, the fold-by-fold
  comparison, a 6-month moving-block bootstrap interval on the monthly IC difference, sleeve
  coverage per fold, the deviation share of score variance, and the measured refit cost in
  CPU-minutes;
* it does **not** produce the pre-registered primary measure (net CNY at 75 000 after the
  gate). That number needs L2's weight mapping and L3's executor, i.e. build step 6, and it
  is computed *from the score file this module writes*. Publishing a CNY difference whose
  weight mapping was chosen after seeing the scores would be the exact error the
  pre-registration exists to prevent, so the file stops at the score and says so.

The decision rule is evaluated only on what exists here: (i) fold majority and (ii) the
bootstrap interval. Condition (iii) — 375 CNY/yr at 75 000 — stays open by construction, so
the honest output of a run today is `unresolved on the monetary clause`, not a verdict.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..panel import aggregate, features, model, source

EVAL_YEARS = tuple(range(2016, 2026))
BOOTSTRAP_BLOCK_MONTHS = 6
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20261104


@dataclass(frozen=True)
class Fold:
    year: int
    train: list[str]
    validate: list[str]
    test: list[str]


def make_folds(dates: list[str]) -> list[Fold]:
    """Expanding-window annual refit.

    ``train`` is every signal date strictly before the test year; ``validate`` is the last
    twelve of those months, used for the ridge penalty and the net's early stop. Expanding
    (not rolling) because ten years is the whole sample: a rolling six-year window would
    throw away the earliest folds, and the pre-registration says annual refit, not
    annual-window refit.
    """
    folds: list[Fold] = []
    for year in EVAL_YEARS:
        cutoff = f"{year}0101"
        train = [d for d in dates if d < cutoff]
        test = [d for d in dates if d[:4] == str(year)]
        if len(train) < 18 or len(test) < 6:
            continue
        folds.append(Fold(year=year, train=train, validate=train[-12:], test=test))
    return folds


def moving_block_bootstrap(series: np.ndarray, *, block: int = BOOTSTRAP_BLOCK_MONTHS,
                           draws: int = BOOTSTRAP_DRAWS, seed: int = BOOTSTRAP_SEED) -> dict:
    """Percentile interval for the mean of a serially dependent monthly series.

    Six-month blocks because the label horizon is 21 sessions and consecutive decisions share
    both overlapping forward windows and an overlapping training set; an iid bootstrap on
    monthly IC differences would report an interval about half as wide as the data supports.
    """
    values = np.asarray([v for v in series if np.isfinite(v)], dtype="float64")
    if len(values) < block * 2:
        return {"mean": float(np.mean(values)) if len(values) else float("nan"),
                "lo": float("nan"), "hi": float("nan"), "draws": 0, "n": len(values)}
    rng = np.random.default_rng(seed)
    n = len(values)
    starts = np.arange(n - block + 1)
    means = np.empty(draws)
    for i in range(draws):
        pick = rng.choice(starts, size=int(np.ceil(n / block)), replace=True)
        sample = np.concatenate([values[s : s + block] for s in pick])[:n]
        means[i] = sample.mean()
    return {
        "mean": float(values.mean()),
        "lo": float(np.quantile(means, 0.05)),
        "hi": float(np.quantile(means, 0.95)),
        "draws": draws,
        "n": int(n),
        "block": block,
    }


def run(*, panel: str | None = None, out_dir: Path | None = None,
        years: tuple[int, ...] = EVAL_YEARS) -> dict:
    started = time.perf_counter()
    out_dir = Path(out_dir) if out_dir else Path("evidence")
    out_dir.mkdir(parents=True, exist_ok=True)
    con = source.connect(panel)
    try:
        dates = source.signal_dates(con, "20130101", f"{max(years)}1231")
        folds = [f for f in make_folds(dates) if f.year in years]
        if not folds:
            raise RuntimeError("no folds: the panel has no signal dates in the evaluation years")
        all_dates = sorted({d for f in folds for d in (*f.train, *f.test)})
        # The scored population is the union of the three indices' weight-file members, not the
        # whole market: a sleeve score is a weighted mean over members, so a name that has never
        # been a member can only dilute the fit. It also keeps the window functions inside the
        # memory budget (3 634 codes against 5 820).
        universe = source.index_member_universe(con)
        frame = features.apply_mask(features.build(con, all_dates, codes=universe))

        folds_out: list[dict] = []
        monthly: list[pd.DataFrame] = []
        sleeves: list[pd.DataFrame] = []
        refit_seconds = 0.0
        for fold in folds:
            # Rows with almost no features are not "cheap observations", they are names the
            # panel cannot describe yet (the 252-day lookbacks are unavailable before 2015).
            # Both arms lose them, and so does the scored cross-section.
            usable = frame[frame["n_finite"] >= features.MIN_FEATURES_FOR_TRAINING]
            train = usable[usable["trade_date"].isin(fold.train)]
            validate = usable[usable["trade_date"].isin(fold.validate)]
            test = frame[frame["trade_date"].isin(fold.test)].copy()
            arms = [model.RidgeArm().fit(train, validate=validate),
                    model.MlpArm().fit(train, validate=validate)]
            row: dict[str, object] = {
                "year": fold.year,
                "train_months": len(fold.train),
                "test_months": len(fold.test),
                "trainable_rows": int((train["entry_ok"] & train["label"].notna()).sum()),
            }
            ics: dict[str, pd.Series] = {}
            for arm in arms:
                score = arm.predict(test)
                score[test["n_finite"].to_numpy() < features.MIN_FEATURES_FOR_TRAINING] = np.nan
                test[f"score_{arm.name}"] = score
                ics[arm.name] = model.monthly_ic(test, f"score_{arm.name}")
                row[f"ic_{arm.name}"] = float(ics[arm.name].mean()) if len(ics[arm.name]) else float("nan")
                row[f"months_{arm.name}"] = int(len(ics[arm.name]))
                row[f"fit_seconds_{arm.name}"] = round(arm.fit_seconds, 2)
                refit_seconds += arm.fit_seconds
                if isinstance(arm, model.RidgeArm):
                    row["lambda"] = arm.chosen_lambda
                else:
                    row["mlp_epochs"] = arm.epochs_run
            diff = (ics["mlp"] - ics["ridge"]).dropna()
            row["ic_diff"] = float(diff.mean()) if len(diff) else float("nan")
            row["mlp_wins"] = int((diff > 0).sum())
            row["mlp_share"] = float((diff > 0).mean()) if len(diff) else float("nan")
            folds_out.append(row)

            for arm_name in ("ridge", "mlp"):
                sleeve = aggregate.sleeve_table(
                    test[["ts_code", "trade_date", f"score_{arm_name}"]].rename(
                        columns={f"score_{arm_name}": "score"}),
                    con, fold.test, prediction_column="score")
                sleeve["arm"] = arm_name
                sleeve["fold"] = fold.year
                sleeves.append(sleeve)
            long_ics = pd.concat(
                {name: series for name, series in ics.items()}, names=["arm", "trade_date"]
            ).reset_index()
            long_ics.columns = ["arm", "trade_date", "ic"]
            long_ics["fold"] = fold.year
            monthly.append(long_ics)

        monthly_frame = pd.concat(monthly, ignore_index=True)
        sleeve_frame = pd.concat(sleeves, ignore_index=True)
        pivot = monthly_frame.pivot_table(index="trade_date", columns="arm", values="ic")
        diff_series = (pivot["mlp"] - pivot["ridge"]).dropna()
        boot = moving_block_bootstrap(diff_series.to_numpy())

        comparisons = [f for f in folds_out if np.isfinite(f["ic_diff"])]
        wins = sum(1 for f in comparisons if f["ic_diff"] > 0)
        shares = [f["mlp_share"] for f in comparisons if np.isfinite(f["mlp_share"])]
        verdict = {
            "folds_compared": len(comparisons),
            "folds_mlp_better": wins,
            "fold_majority_70pct": bool(comparisons) and wins / len(comparisons) >= 0.70,
            "mean_fold_share_mlp_better": float(np.mean(shares)) if shares else float("nan"),
            "bootstrap_ci_excludes_zero": bool(np.isfinite(boot["lo"]) and (boot["lo"] > 0 or boot["hi"] < 0)),
            "monetary_clause": "open — computed by build step 6 from sleeve_scores.parquet",
            "adopt_nonlinearity": False,
        }
        verdict["adopt_nonlinearity"] = bool(
            verdict["fold_majority_70pct"]
            and verdict["bootstrap_ci_excludes_zero"]
            and np.isfinite(boot["mean"]) and boot["mean"] > 0
        )

        sleeves_by_arm = {
            arm: aggregate.deviation_share(group)
            for arm, group in sleeve_frame.groupby("arm", observed=True)
        }
        coverage = sleeve_frame.groupby(["arm", "fold"], observed=True)["coverage"].mean()

        summary = {
            "generated": pd.Timestamp.now(tz="UTC").isoformat(),
            "panel": str(panel or source.DEFAULT_PANEL),
            "eval_years": list(years),
            "signal_dates": {"first": min(all_dates), "last": max(all_dates), "count": len(all_dates)},
            "folds": folds_out,
            "bootstrap": boot,
            "verdict": verdict,
            "deviation_share": {arm: stats for arm, stats in sleeves_by_arm.items()},
            "mean_coverage": {f"{arm}/{fold}": float(v) for (arm, fold), v in coverage.items()},
            "refit_cpu_minutes": round(refit_seconds / 60.0, 2),
            "wall_seconds": round(time.perf_counter() - started, 1),
            "features": list(features.FEATURES),
            "inputs": list(model.INPUT_COLUMNS),
            "notes": [
                "primary measure (net CNY at 75 000 after the gate) belongs to build step 6; "
                "this file ends at the score",
                "index weights are one month stale by construction: at a month-end signal the "
                "newest snapshot has available_date after the signal, so the prior month is used",
                "coverage is reported per fold; a sleeve score over a small covered weight is not "
                "a statement about the ETF",
            ],
        }
        # Explicit utf-8: Windows defaults write_text to the locale code page, which mangles
        # the report's dashes and arrows and then cannot be read back as utf-8.
        (out_dir / "e1-summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        monthly_frame.to_parquet(out_dir / "e1-monthly-ic.parquet", index=False)
        sleeve_frame.to_parquet(out_dir / "sleeve_scores.parquet", index=False)
        (out_dir / "e1-report.md").write_text(render(summary), encoding="utf-8")
        return summary
    finally:
        con.close()


def render(summary: dict) -> str:
    v = summary["verdict"]
    b = summary["bootstrap"]
    lines = [
        "# E1 — panel predictability, ridge vs a small MLP",
        "",
        f"- generated: {summary['generated']}",
        f"- panel: `{summary['panel']}`",
        f"- signal dates: {summary['signal_dates']['first']} … {summary['signal_dates']['last']} "
        f"({summary['signal_dates']['count']} months)",
        f"- features: {len(summary['features'])}, inputs incl. coverage: {len(summary['inputs'])}",
        "",
        "## Folds (expanding window, annual refit)",
        "",
        "| year | train mo | test mo | trainable rows | IC ridge | IC mlp | ΔIC | MLP better | λ | mlp epochs |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for f in summary["folds"]:
        lines.append(
            f"| {f['year']} | {f['train_months']} | {f['test_months']} | {f['trainable_rows']:,} | "
            f"{f['ic_ridge']:.4f} | {f['ic_mlp']:.4f} | {f['ic_diff']:+.4f} | "
            f"{f['mlp_wins']}/{f['months_mlp']} | {f.get('lambda', '')} | "
            f"{f.get('mlp_epochs', '')} |"
        )
    lines += [
        "",
        "## Decision rule (§6), as far as this file can evaluate it",
        "",
        f"- (i) MLP ≥ ridge in ≥ 70 % of folds: **{v['folds_mlp_better']}/{v['folds_compared']}** "
        f"folds → {'pass' if v['fold_majority_70pct'] else 'fail'}",
        f"- (ii) 90 % moving-block bootstrap of the monthly ΔIC excludes zero: "
        f"mean {b['mean']:+.4f}, CI [{b['lo']:+.4f}, {b['hi']:+.4f}] "
        f"({b['draws']} draws, {b.get('block', '')}-month blocks, n={b['n']}) → "
        f"{'pass' if v['bootstrap_ci_excludes_zero'] else 'fail'}",
        f"- (iii) Δ net CNY ≥ 375/yr at 75 000: **{v['monetary_clause']}**",
        "",
        f"**Adopt nonlinearity: {v['adopt_nonlinearity']}.** "
        + ("All three clauses passed." if v["adopt_nonlinearity"] else
           "A clause failed or the monetary clause is unevaluated, so the conforming reading is "
           "`ridge ships` only if (i)/(ii) failed; with (iii) open the run is *unresolved on the "
           "monetary clause* and this file does not convert it into a verdict."),
        "",
        "## Secondary, reported whether or not it passes",
        "",
        f"- refit cost: **{summary['refit_cpu_minutes']} CPU-minutes** for all folds and both arms "
        f"(wall {summary['wall_seconds']} s) — this is the number F-113a8e8d-5 asked for",
        f"- deviation share of sleeve-score variance: "
        + ", ".join(
            f"`{arm}` {s['deviation_share']:.3f} (n={int(s['months'])} sleeve-months)"
            for arm, s in summary["deviation_share"].items()
            if np.isfinite(s.get("deviation_share", float("nan")))
        ),
        "- mean sleeve coverage by fold: "
        + ", ".join(f"`{k}` {val:.2f}" for k, val in list(summary["mean_coverage"].items())[:12]),
        "",
        "## Recorded limitations",
        "",
    ]
    lines += [f"- {note}" for note in summary["notes"]]
    lines.append("")
    return "\n".join(lines)


def main(out_dir: str | None = None) -> dict:
    summary = run(out_dir=Path(out_dir) if out_dir else None)
    print(render(summary))
    return summary


if __name__ == "__main__":
    main()
