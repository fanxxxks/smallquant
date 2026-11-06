# E1 — panel predictability, ridge vs a small MLP

- generated: 2026-11-04T12:47:37.420435+00:00
- panel: `D:/minequant/AlphaGPT/data/ashare_v2.duckdb`
- signal dates: 20130131 … 20161230 (48 months)
- features: 14, inputs incl. coverage: 15

## Folds (expanding window, annual refit)

| year | train mo | test mo | trainable rows | IC ridge | IC mlp | ΔIC | MLP better | λ | mlp epochs |
|---|---|---|---|---|---|---|---|---|---|
| 2016 | 36 | 12 | 55,448 | 0.1340 | 0.1282 | -0.0059 | 4/12 | 100.0 | [21, 18] |

## Decision rule (§6), as far as this file can evaluate it

- (i) MLP ≥ ridge in ≥ 70 % of folds: **0/1** folds → fail
- (ii) 90 % moving-block bootstrap of the monthly ΔIC excludes zero: mean -0.0059, CI [-0.0206, -0.0059] (2000 draws, 6-month blocks, n=12) → pass
- (iii) Δ net CNY ≥ 375/yr at 75 000: **open — computed by build step 6 from sleeve_scores.parquet**

**Adopt nonlinearity: False.** A clause failed or the monetary clause is unevaluated, so the conforming reading is `ridge ships` only if (i)/(ii) failed; with (iii) open the run is *unresolved on the monetary clause* and this file does not convert it into a verdict.

## Secondary, reported whether or not it passes

- refit cost: **0.16 CPU-minutes** for all folds and both arms (wall 19.5 s) — this is the number F-113a8e8d-5 asked for
- deviation share of sleeve-score variance: `mlp` 1.000 (n=36 sleeve-months), `ridge` 1.000 (n=36 sleeve-months)
- mean sleeve coverage by fold: `mlp/2016` 0.93, `ridge/2016` 0.93

## Recorded limitations

- primary measure (net CNY at 75 000 after the gate) belongs to build step 6; this file ends at the score
- index weights are one month stale by construction: at a month-end signal the newest snapshot has available_date after the signal, so the prior month is used
- coverage is reported per fold; a sleeve score over a small covered weight is not a statement about the ETF
