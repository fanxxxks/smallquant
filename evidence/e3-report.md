# E3 — the board lot's cost at 50 000 CNY, priced in CNY

_run `run-e3c00001-50k0-4c01-9a00-000000000001` · cell `nav50000_tol15.1_measured` · 15.1 bp per-order gate · 2016-01-04 .. 2025-12-31 · 22.8 s_

## 1. Control check (P1) — first, because nothing else means anything without it

Verdict: **`control-reproduces-e2`**

| clause | measured | E2 | ok |
|---|---|---|---|
| nav_end | `62163.64` | `62163.64` | yes |
| n_fills | `6` | `6` | yes |
| ledger_head | `db6a4f19b62d1e759bd1c6177dee140f6c5cc46c5e6357053ed78b35cf07f1e9` | `db6a4f19b62d1e759bd1c6177dee140f6c5cc46c5e6357053ed78b35cf07f1e9` | yes |

## 2. Terminal value and risk, one cell, one window

| arm | nav_end | CAGR | vol | max DD | cost bp/yr | turnover/yr | fills | intents | TE | granularity | gate |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `static` | 62,164 | 2.20 % | 9.40 % | -19.17 % | 0.75 | 0.106 | 6 | 102 | 33.17 % | 12.35 % | 26.79 % |
| `lots` | 85,111 | 5.46 % | 8.63 % | -12.27 % | 1.67 | 0.195 | 14 | 65 | 16.30 % | 6.24 % | 17.81 % |
| `lots_deploy` | 91,610 | 6.24 % | 8.99 % | -13.69 % | 1.86 | 0.236 | 15 | 67 | 22.49 % | 5.50 % | 23.95 % |
| `cash` | 50,000 | 0.00 % | 0.00 % | 0.00 % | 0.00 | 0.000 | 0 | 0 | 0.00 % | 0.00 % | 0.00 % |

TE splits into the part the board lot makes unavoidable (`granularity`) and the part the
per-order gate then adds (`gate`). A composition is only better if it lowers the sum,
not if it moves weight from one to the other.

### Day one, reconstructed from the fills

Read at the close of the entry session, not at the first month end: January 2016 was an
equity crash, which flatters any arm that failed to buy equity.

| arm | invested | cash | equity | bond | commodity | overseas | codes | entry cost |
|---|---|---|---|---|---|---|---|---|
| `static` | 62.61 % | 37.39 % | 41.96 % | 20.65 % | 0.00 % | 0.00 % | 3 | 18 |
| `lots` | 80.43 % | 19.57 % | 39.72 % | 20.63 % | 10.22 % | 9.86 % | 5 | 30 |
| `lots_deploy` | 98.07 % | 1.93 % | 51.98 % | 20.83 % | 12.66 % | 12.61 % | 5 | 31 |
| `cash` | n/a | 100.00 % | n/a | n/a | n/a | n/a | 0 | n/a |

## 3. Sleeve realisation — aimed versus held, and how many members the tree kept

### `static`

| sleeve | aimed first | realised first | aimed last | realised last | gap mean | members first → last decision | months >2 pp short |
|---|---|---|---|---|---|---|---|
| equity | 45.00 % | 36.73 % | 45.00 % | 44.72 % | 1.03 % | 2 → 3 | 65 |
| bond | 35.00 % | 22.37 % | 35.00 % | 36.20 % | 6.62 % | 1 → 2 | 61 |
| commodity | 10.00 % | 0.00 % | 10.00 % | 0.00 % | 10.00 % | 2 → 2 | 120 |
| overseas | 10.00 % | 0.00 % | 10.00 % | 0.00 % | 10.00 % | 3 → 3 | 120 |

### `lots`

| sleeve | aimed first | realised first | aimed last | realised last | gap mean | members first → last decision | months >2 pp short |
|---|---|---|---|---|---|---|---|
| equity | 43.72 % | 34.75 % | 44.18 % | 32.33 % | 6.77 % | 2 → 3 | 106 |
| bond | 22.33 % | 22.33 % | 32.83 % | 26.04 % | 2.17 % | 1 → 2 | 60 |
| commodity | 9.51 % | 11.62 % | 8.38 % | 6.56 % | -2.43 % | 1 → 2 | 9 |
| overseas | 9.78 % | 9.78 % | 9.87 % | 10.29 % | -2.70 % | 1 → 1 | 0 |

### `lots_deploy`

| sleeve | aimed first | realised first | aimed last | realised last | gap mean | members first → last decision | months >2 pp short |
|---|---|---|---|---|---|---|---|
| equity | 53.21 % | 46.67 % | 46.07 % | 36.89 % | 13.31 % | 2 → 3 | 119 |
| bond | 23.14 % | 23.14 % | 33.45 % | 27.91 % | 0.02 % | 1 → 2 | 48 |
| commodity | 11.83 % | 14.78 % | 10.24 % | 13.47 % | -3.08 % | 1 → 2 | 0 |
| overseas | 11.83 % | 12.84 % | 10.24 % | 11.02 % | -2.64 % | 1 → 1 | 0 |

### `cash`

| sleeve | aimed first | realised first | aimed last | realised last | gap mean | members first → last decision | months >2 pp short |
|---|---|---|---|---|---|---|---|
| equity | 0.00 % | 0.00 % | 0.00 % | 0.00 % | 0.00 % | 2 → 3 | 0 |
| bond | 0.00 % | 0.00 % | 0.00 % | 0.00 % | 0.00 % | 1 → 2 | 0 |
| commodity | 0.00 % | 0.00 % | 0.00 % | 0.00 % | 0.00 % | 2 → 2 | 0 |
| overseas | 0.00 % | 0.00 % | 0.00 % | 0.00 % | 0.00 % | 3 → 3 | 0 |

## 4. The idle cash, priced

First-order: the cash the account held missed the mandate's own return for the next
month, compounded at the account's growth. Cross terms are excluded on purpose — this
is the *idle cash* part of the gap, not the whole arm difference.

| arm | idle-cash drag (CNY) | bp of NAV0 per year | months priced |
|---|---|---|---|
| `static` | 11,252 | 254.2 | 119 |
| `lots` | 6,297 | 142.0 | 119 |
| `lots_deploy` | 3,010 | 70.3 | 119 |
| `cash` | 48,948 | 987.2 | 119 |

## 5. Paired differences (P3/P4) — 6-month moving-block bootstrap, 2 000 draws

| pair | annual CNY | 90 % interval | MDE CNY/yr | separates from zero | reading |
|---|---|---|---|---|---|
| `lots-static` | +1,543 | [858, 2,213] | 1,393 | yes | measurable |
| `lots_deploy-static` | +1,930 | [1,150, 2,784] | 1,667 | yes | measurable |
| `lots_deploy-lots` | +387 | [-72, 974] | 933 | no | unmeasurable at this capital |
| `lots-cash` | +2,851 | [1,264, 5,027] | 3,819 | yes | measurable |
| `lots_deploy-cash` | +3,238 | [1,768, 5,494] | 3,978 | yes | measurable |

Adoption verdict: **`adopt-measurable-composition`** — adopted `lots`

Tie-break: redeploy's gain over cash-residual does not separate from zero, so the lower-risk form is kept.

**Read §9 before quoting this verdict.** "Measurable" here means the interval excludes zero for the *pair as replayed*. The ablation in §9 shows the pair differs in sleeve exposure as well as in lot rule, and that the whole difference is the exposure. The verdict survives as `lots` over `static` and `lots_deploy`; it does not survive as attribution.

## 6. Capital floor, descriptive only (P5)

`aimed` is the decision target after whole lots; `realised` is the same sleeve a month later, so it also contains the sleeve's own price drift and is NOT a quantisation measure. The quantisation column is `aimed` against the 35 % mandate.

| arm | nav_end | bond aimed entry | bond aimed last | quantisation pp | cash mean | fills |
|---|---|---|---|---|---|---|
| `static` | 204,383 | 34.41 % | 35.00 % | 0.0 | 9.35 % | 26 |
| `lots` | 219,061 | 34.44 % | 34.43 % | 0.6 | 4.94 % | 29 |

At 50,000 the same cell quantises the bond sleeve by 2.2 pp. The capital-floor option is therefore real and small: it buys about a point of sleeve fidelity for 2.4x the capital, while the lot form buys the whole measured composition gain at the capital the mandate names.

## 7. Congruence with the probe that made `bond-sleeve-lot-bound`

At 2016-01-04, NAV 50000: **DISAGREES** — probe total 6 instruments vs engine 5.

| sleeve | probe max_feasible_k | engine k | unlisted at ref | agrees | cause |
|---|---|---|---|---|---|
| equity | 3 | 2 | 512100 | NO | probe counted 1 unlisted member(s): 512100 |
| bond | 1 | 1 | 511380 | yes | — |
| commodity | 1 | 1 | — | yes | — |
| overseas | 1 | 1 | — | yes | — |

## 8. What this licenses

- The E2 execution left 40.90 % of the account in cash at entry and never bought the commodity or overseas sleeve at all; the lot-defined composition enters with 21.53 % cash and holds 1 commodity and 1 overseas member(s) on day one.
- Terminal value: `lots` 85,111 vs `lots_deploy` 91,610 vs `static` 62,164 vs `cash` 50,000 on the same 2016-01-04 .. 2025-12-31 window.
- `lots-static`: +1,543 CNY/yr, 90 % interval [858, 2,213], MDE 1,393 — measurable.
- `lots_deploy-lots`: +387 CNY/yr, 90 % interval [-72, 974], MDE 933 — unmeasurable at this capital.
- Adoption rule (P4) returns `adopt-measurable-composition`: a composition whose interval excludes zero is adopted.
- The idle cash is worth 6,297 first-order for `lots` and 3,010 for `lots_deploy`: that is the size of the object design v13 did not have.
- The composition probe's instrument counts are one too high at 2016-01-04 for equity: it skipped members without a price instead of dropping them from the tree, so it counted a fund that had not listed. The bond conclusion the probe was run for is unaffected (bond agrees), the instrument total is: probe 6 vs engine 5.

## 9. Attribution and the measurement ceiling — added after the ablation (ledger seq 98-108)

Sections 1-8 measure the pair as replayed. They cannot say *why* it separates, because `static`
never held commodity or overseas in any of 120 months (realised mean 0.000 in both sleeves) while
`lots` held 0.119 and 0.125. A pair that differs in exposure as well as in mechanism attributes
nothing to the mechanism. The ablation removes one sleeve at a time from **both** arms, leaving the
removed weight in cash with no renormalisation, so the only thing that changes between arms is
which sleeves exist. Source: `probe/ablation_e3.py`, `evidence/probe-ablation/summary.json`,
pre-declared rule at seq 98 (retain the lot-rule reading only if the both-sleeves removal keeps at
least 60 % of the full difference, ~925 CNY/yr).

| variant | lots − static CNY/yr | 90 % interval | share of full | pre-declared reading |
|---|---|---|---|---|
| `full` | +1,542.8 | [857.8, 2,212.6] | 1.000 | reproduces §5 to the cent |
| `no_commodity` | +959.7 | [524.8, 1,496.9] | 0.622 | half the effect is still there |
| `no_overseas` | +742.8 | [253.1, 1,041.0] | 0.481 | half the effect is still there |
| `no_both` | −19.6 | [−99.4, +28.7] | −0.013 | retain fails: 1.3 % < 60 % |
| `no_bond` | +1,773.4 | — | 1.149 | the effect is not in the bond sleeve |

Single-sleeve removals each retain about half because the two sleeves are substitutes: the freed
weight goes to cash, and the remaining sleeve plus the extra cash reproduces most of the
composition. Remove both and nothing is left. The result is not a 50,000 artefact — the same
removal collapses the difference at 75,000 (full +1,910.0 → `no_both` −103.5) and at 100,000
(full +1,166.7 → −47.9).

Conclusion (seq 100): the lot-defined mandate's measured gain is **acquiring the commodity and
overseas sleeves**, not the lot arithmetic. The lot rule is what makes those sleeves affordable at
this capital; it is not itself the return. Any future statement that the composition form earns
+1,543 CNY/yr has to be read as "the book that can hold four sleeves earns it".

### The ceiling any forward test runs into (seq 101)

Same estimator, same window, difference series truncated to each half:

| quantity | annual CNY | 10-year MDE | 60-month MDE (1st / 2nd half) |
|---|---|---|---|
| `lots-static` | +1,542.8 | 1,393.3 | 1,666.2 / 2,244.3 |
| `lots-cash` | +2,851.2 | 3,819.2 | 6,007 / 4,770 |

A five-year forward book scored net CNY against cash would have an MDE roughly twice the effect it
is looking for. Reaching MDE = effect needs ~18 years for `lots-cash` and ~10.6 for `lots-static`
at the measured 8.63-9.40 % vol. So the forward book cannot license a return claim at this
capital; what it can license is execution conformance.

### What the forward book therefore measures (seq 102, 103, 106)

Dry run of the acceptance test against the existing artefacts (`probe/conformance_dryrun.py`,
`evidence/probe-conformance/dryrun.json`, run-f6bb9443): sleeve occupancy 120/120 months for
commodity and overseas, cost 1.6718 bp of NAV/yr, both ledger heads reproduced exactly, and the
drift-free conformance measure is intent fill ratio = filled lots / (filled + suppressed intent):
equity 0.334, bond 0.475, commodity 0.507, overseas 0.561. Two criteria were mis-specified by the
dry run and amended at seq 106: `insufficient_settled_cash` is a venue constraint and belongs in
the admissible suppression set (2 occurrences, both bond), and the "realised-vs-aimed gap > 2 pp"
line was void because a monthly weight carries price drift — equity's 6.77 pp mean gap is drift,
while 25 of its 27 suppressions are the code's clearing floor. Note the scale of that floor: median
intent 1,888.5 CNY against a per-code clearing minimum of 3,345-5,066 CNY, with 75.4 % of intents
below it.
