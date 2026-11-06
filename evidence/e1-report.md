# E1 — panel predictability, ridge vs a small MLP

- generated: 2026-11-04T12:57:00.519260+00:00
- panel: `D:/minequant/AlphaGPT/data/ashare_v2.duckdb`
- signal dates: 20130131 … 20251231 (156 months)
- features: 14, inputs incl. coverage: 15

## Folds (expanding window, annual refit)

| year | train mo | test mo | trainable rows | IC ridge | IC mlp | ΔIC | MLP better | λ | mlp epochs |
|---|---|---|---|---|---|---|---|---|---|
| 2016 | 36 | 12 | 50,255 | 0.0999 | 0.1063 | +0.0064 | 8/12 | 100.0 | [20, 28] |
| 2017 | 48 | 12 | 77,919 | -0.0528 | -0.0371 | +0.0157 | 7/12 | 0.3 | [13, 24] |
| 2018 | 60 | 12 | 108,138 | 0.0840 | 0.0416 | -0.0423 | 2/12 | 0.3 | [21, 4] |
| 2019 | 72 | 12 | 140,541 | 0.0262 | 0.0321 | +0.0059 | 6/12 | 100.0 | [9, 14] |
| 2020 | 84 | 12 | 175,336 | 0.0352 | 0.0375 | +0.0023 | 7/12 | 100.0 | [22, 10] |
| 2021 | 96 | 12 | 211,698 | 0.0890 | 0.1005 | +0.0115 | 6/12 | 100.0 | [21, 23] |
| 2022 | 108 | 12 | 249,838 | 0.1054 | 0.1296 | +0.0242 | 10/12 | 100.0 | [10, 11] |
| 2023 | 120 | 12 | 289,256 | 0.1222 | 0.1277 | +0.0055 | 8/12 | 100.0 | [9, 12] |
| 2024 | 132 | 12 | 329,515 | 0.0356 | 0.0618 | +0.0263 | 9/12 | 100.0 | [19, 10] |
| 2025 | 144 | 12 | 368,233 | 0.1022 | 0.0980 | -0.0042 | 5/12 | 100.0 | [7, 6] |

## Decision rule (§6), as far as this file can evaluate it

- (i) MLP ≥ ridge in ≥ 70 % of folds: **8/10** folds → pass
- (ii) 90 % moving-block bootstrap of the monthly ΔIC excludes zero: mean +0.0051, CI [-0.0045, +0.0137] (2000 draws, 6-month blocks, n=120) → fail
- (iii) Δ net CNY ≥ 375/yr at 75 000: **open — computed by build step 6 from sleeve_scores.parquet**

**Adopt nonlinearity: False.** A clause failed or the monetary clause is unevaluated, so the conforming reading is `ridge ships` only if (i)/(ii) failed; with (iii) open the run is *unresolved on the monetary clause* and this file does not convert it into a verdict.

## Secondary, reported whether or not it passes

- refit cost: **2.96 CPU-minutes** for all folds and both arms (wall 261.9 s) — this is the number F-113a8e8d-5 asked for
- deviation share of sleeve-score variance: `mlp` 0.324 (n=360 sleeve-months), `ridge` 0.401 (n=360 sleeve-months)
- mean sleeve coverage by fold: `mlp/2016` 0.93, `mlp/2017` 0.94, `mlp/2018` 0.96, `mlp/2019` 1.00, `mlp/2020` 1.00, `mlp/2021` 1.00, `mlp/2022` 1.00, `mlp/2023` 1.00, `mlp/2024` 1.00, `mlp/2025` 1.00, `ridge/2016` 0.93, `ridge/2017` 0.94

## Recorded limitations

- primary measure (net CNY at 75 000 after the gate) belongs to build step 6; this file ends at the score
- index weights are one month stale by construction: at a month-end signal the newest snapshot has available_date after the signal, so the prior month is used
- coverage is reported per fold; a sleeve score over a small covered weight is not a statement about the ETF
