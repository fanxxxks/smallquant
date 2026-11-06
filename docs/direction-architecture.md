# newquant — direction v4 / architecture v7

Living spec. Supersedes §6–§9 of `D:/newquant/docs/new-project-direction-and-plan.md`
(that file stays as the review history; its numbers are still the cited evidence).
Ledger: idea `etf-implementable-frontier` v4, design v7, task `etf-implementable-frontier`.
Conditions: `D:/newquant/.quant/project.json` — CN A-share ETF book, 50 000–100 000 CNY,
monthly decisions, research + paper only.

Every claim below carries the condition under which it holds and the measure that would
show it false. A claim with neither is not a claim.

---

## 1. Direction (one paragraph)

The binding constraint at 50 000–100 000 CNY is not forecast accuracy but the number of
independent, cost-clearable decisions an account of that size can take in a year. So the
project splits estimation breadth from holding breadth:

- **estimation** runs where statistical power exists — the A-share daily panel
  (`D:/minequant/AlphaGPT/data/ashare_v2.duckdb`, 12 008 787 rows, 5 820 codes,
  2014-01-02 … 2026-10-15) plus an ETF panel — millions of rows per refit;
- **holding** is five ETF sleeves (equity / bond / commodity / overseas / cash) rebalanced
  at most monthly, target turnover ≤ 6 per year;
- **the only interface between them** is a small vector of sleeve scores per month
  (expected excess, expected vol, expected shortfall), combined into weights by a rule with
  **≤ 4 fitted parameters** — a test asserts that count;
- **every order passes a post-rounding cost gate inside an append-only ledger**, and the
  score that counts is net CNY.

The neural network is a *comparison arm at the panel layer*, never at the allocation layer:
a model fitted on ~900 basket-months is capped near 18 parameters by a 50-observations-per-
parameter budget, which admits a rule or a tight linear model and rejects a network by
construction (ledger fact `nn-belongs-at-panel-layer`, seq 41). Whether nonlinearity earns
its place is settled by E1, not by preference.

**What this direction does not claim**, after the prior-art check of 2026-11-04 (see 11):

- Not that holding breadth is capped by fees. That is Baule (2010), *OR Spectrum* 32:61-76,
  abstract and Table 2: minimum per-position fees force a small investor into a few names and
  the optimum is `n* = 2-3` at this capital. We are *predicted* by that literature, not ahead
  of it, and the four-sleeve book is justified only by measuring whether it clears the gate.
- Not that a few-parameter combiner is an advance. That is Brandt-Santa-Clara-Valkanov (2009).
  Our split is defended by parameter count alone (900 basket-months at 50 obs/parameter gives
  about 18 parameters at the holding layer), which is also the argument BSCV use *against*
  splitting; the split is therefore a stated trade-off, not a contribution.
- Not that an append-only hash chain is novel. That is Crosby-Wallach (2009) "tamper-evident
  logging"; we use its vocabulary for I-6 and claim no more.

**What it does claim.** One object that no cited model can express: every model above has a
never-empty feasible set — continuous weights, proportional costs, or a lot handled inside an
MILP — so none can say "this order, at this capital, is not admissible". This project measures
the **admissibility** of the order, not the optimum inside an admissible set: the number of
(month x instrument) cells that clear the gate at a given NAV and tolerance, and the size of
the smallest executable action. That is what makes `not measurable at this capital` a verdict
distinct from `no edge`. The honest version of the claim says the metric is new, not the
question: Concretum states the question in a blog post and Baule answers a neighbouring one.

**It also does not claim** alpha from static premia, or that a risk model beats the market.
A null E1 leaves the account engine plus a measured feasibility map, and closes the prediction
branch by evidence rather than fatigue.

**One citation to answer before anyone else raises it.** Garleanu-Pedersen (*JF* 2013, after
eq. 10) write that "a larger absolute risk aversion can also be viewed as a smaller investor,
for whom transaction costs play a smaller role, and who therefore trades closer to her aim".
Under their quadratic cost that is right. A fixed per-order floor breaks the argument, because
the cost stops scaling with the trade, and Altarovici-Reppen-Soner (*SIAM J. Control Optim.*
2017, 5.7) state the same wealth dependence in the opposite direction: "at low wealth levels,
fixed transaction costs are the predominant cost consideration". Our premise is their
fixed-cost branch, not their proportional-cost branch, and the doc says so instead of citing
GP as support.

---

## 2. Answers to the six open objections (this is the substance of v4)

Round `round-8d9f917d` blocked on five highs plus one medium. Each is answered by a design
change, a measurement with a pre-declared rule, or both. None is answered by re-wording.

| id | objection, in its own terms | answer in v7 | status |
|---|---|---|---|
| F-113a8e8d-5 | 900 basket-months caps a basket-level fit at ~18 params, so a network deterministically trips the fallback; a network can only execute if estimation happens on the stock panel first — which contradicts `scale: trivial CPU on 900 rows` | Training moves to the panel layer. The `scale` claim is **replaced**: refit cost is 12M rows × ~60 features × 13 annual refits, to be *measured* in build step 3 and reported in CPU-minutes; no claim of triviality. A contract test asserts the sleeve combiner has ≤ 4 fitted parameters. | answered by amendment |
| F-113a8e8d-4 | a realised-drawdown check cannot enforce a prospective 27 % ceiling under monthly trading and gaps | The ceiling becomes **a construction plus a rejection rule**, both in the allocator, neither inferred afterwards: (i) *ex ante* — target weights are chosen so the book's 1-month 95 % VaR ≤ d_max/6, so six consecutive worst months land at the ceiling before any rebalance evidence arrives; (ii) *state throttle* — when book drawdown from running peak > d_max/2, the equity target is halved until the peak recovers; (iii) *rejection* — any walk-forward or paper path whose running drawdown exceeds d_max fails the mandate and the candidate is rejected regardless of return. | answered by construction + rule |
| F-113a8e8d-2 | separating estimation breadth from holding breadth does not establish a new predictive contribution; missing: panel-trained nonlinear model improves executable monthly outcomes over a linear model on the same factors | E1 (§6) is exactly that comparison: identical features, identical folds, identical account engine, ridge vs MLP, net CNY. Pre-declared adoption rule; ridge is the default and nonlinearity must win under it. | answered by preregistered experiment |
| F-113a8e8d-3 | failure of one timing rule is not evidence against learned predictors in general | The claim under test is narrowed to what can be falsified at this sample: *does nonlinearity add monthly, cost-clearable information at this panel size?* No claim about "learned predictors" as a class is made or rejected. E1 is labelled a complexity benchmark in the preregistration so the result cannot be over-read later. | answered by scope narrowing |
| F-113a8e8d-1 | 900 basket-months overstates the information behind a common monthly timing target; needs sleeve-specific information and dependence-preserving uncertainty | The sleeve score is decomposed into a common monthly factor and sleeve deviations (cross-sectional mean removed; residuals reported). Uncertainty uses a **moving-block bootstrap over calendar dates in 6-month blocks**, which preserves both autocorrelation and cross-sleeve correlation by resampling whole blocks of months, not individual months. Pre-declared: if the sleeve-deviation share of score variance is below 20 %, the design states that the book is a single market-timing bet and reports it as such rather than as allocation skill. | answered by design + measurement |
| F-113a8e8d-6 | at 50 k the fee floor forces marginal adjustments into `FIXED`, so a learned monthly signal may be indistinguishable in realised fills from a coarse 2–3 parameter rule | Restated after the 2026-11-04 review, because the original answer conflated two things. The gate is applied to the **post-rounding** notional. What it destroys is not measurability but **resolution**: the smallest executable action is `N_min(T)/NAV` — 10.0 % of NAV at 50 k on a 15.1 bp tolerance, 6.7 % at 75 k, 5.0 % at 100 k (`evidence/feasibility-*.md` section E). The annual cap is a *pool*, not a monthly allowance: at 50 k / 15.1 bp it funds **52** such lumps, so the budget is not binding and the lump size is. Measurability is therefore decided by a **power** statement, not by a cleared-cell share: the arm must show that the achievable minimum detectable net difference, given the number of independent monthly decisions and the measured dispersion of the monthly net-CNY difference, is below the 375 CNY/yr hurdle. If it is not, the verdict is `unmeasurable at this capital` — a statement about resolution and power, with its number, not a 50 % threshold. | answered by measurement contract, revised |

The four `F-60b5f78a-*` objections belong to the retired band-rule line and are closed by
decision `band-line-closed` (§8): the band rule is a reported sensitivity, not a shipped rule,
so its stamp-duty inconsistency and its exposure-drift question no longer gate anything; the
dividend/split one is closed by construction because `corp_actions` is now a layer-0 input and
invariant I-4 (§5) makes the ex-date cash change a test, not a hope.

---

## 3. Return source, named

Three candidate sources, each with the measure that would kill it. Only the first is in v1.

1. **Volatility-conditioned exposure (in v1).** Realised volatility and correlation are far
   more forecastable than returns; a book that trims equity exposure when its own forecast
   vol is high and re-adds when it is low has a documented, testable effect and — decisive
   here — it is implementable with ≤ 6 orders a year at this capital. Killed by: E2 shows the
   vol-conditioned arm's net CNY indistinguishable from buy-and-hold of the equity sleeve
   across walk-forward folds.
2. **Sleeve-level relative value from panel breadth (E1 branch).** Panel model → aggregate
   breadth/score features per sleeve → deviation from the common factor. Killed by E1's null
   result.
3. **Static premia (fallback).** Bond–equity–gold premium harvesting with annual rebalance.
   Not alpha, and it is labelled a bet wherever it appears.

---

## 4. Architecture

Five layers, one direction of data, one place where state lives. The loop closes only at the
ledger.

```
 L0  frozen inputs (hashed, never mutated in place)
     panel.duckdb (stocks)   etf_bars.parquet   corp_actions.parquet   instrument.parquet
             |                     |                    |                     |
             +-------- as-of session view (features use data <= t-1 close) --+
                                    |
 L1  panel estimation (offline, monthly refit, walk-forward)
     features(t) -> model {ridge | mlp} -> stock scores -> sleeve aggregation
                                    |
                          sleeve_scores.parquet  (mu, sigma, es per sleeve per month)
                                    |
 L2  allocation (tiny, <= 4 fitted parameters)
     mandate + scores + current book -> target weights (VaR-capped, drawdown throttled)
                                    |
 L3  execution gate + ledger (append-only, hash-chained, deterministic replay)
     lot rounding -> post-rounding cost gate -> sells first -> buys from settled cash
                                    |
 L4  evaluation (net CNY, block bootstrap, rejection rules)
     daily.csv  decision.json  paper_book/
```

Module map (nothing else may hold state):

| path | job | must not |
|---|---|---|
| `newquant/data/freeze.py` | build + hash L0 artefacts | read anything after the freeze date |
| `newquant/panel/features.py` | PIT panel features | touch a column dated after `t` |
| `newquant/panel/model.py` | `Ridge` (numpy, closed form) + `MLP` (torch, panel rows) | fit on basket-months |
| `newquant/panel/aggregate.py` | stock scores → sleeve scores | use a future constituent list |
| `newquant/sleeve/combine.py` | scores → weights, ≤ 4 fitted params | exceed its parameter budget (asserted) |
| `newquant/book/order.py` | lot rounding + cost gate + settlement | resize a failing order (suppress it) |
| `newquant/ledger/store.py` | append-only JSONL, hash chain, NAV | rewrite a historical record |
| `newquant/eval/report.py` | net curve, block bootstrap, decision rule | evaluate on a `final` window more than once |

Instrument metadata is the table the rest is correct against — settlement is per class and is
**not** uniformly T+1. **Frozen and measured** (`data/venue.parquet`, hash `d6a6e438`, built by
`newquant/data/freeze.py` from 45,197 bars of 15 codes, 2013-01-04 … 2026-11-04):

```
sleeve    members (one lot, CNY)                                      settle  tradable
equity    510300 (418) 510500 (666) 159915 (256) 512100 (265)          T+1    all four
bond      511220 (1044) 511380 (1254)                                  T+0    both
          511010 (14135)* 511260 (13578)*                              T+0    no -- lot
commodity 518880 (823) 159934 (860)                                    T+0    both
overseas  513100 (224) 513500 (261) 159920 (140)                       T+1    all three
cash      511880 (10093)* 511990 (9999)*                               T+0    no -- lot
CASH      residual balance, not an instrument                           T+0    yes, costless
```
`*` one lot exceeds 10 % of a 50 k NAV (13-28 % across 50/75/100 k), so the position cannot be
sized without the lot dominating its weight. Two consequences, both measured, not stylistic:

1. **Cash is the residual balance, not 511990/511880.** Cash left uninvested has zero
   commission, T+0 availability and no lot granularity, so a cash ETF is strictly dominated at
   this capital. The sleeve is real, the instrument is not.
2. **The bond sleeve is 511220/511380 only.** The two 13 k-lot treasuries are out of reach
   below ~200 k NAV.

Fee profile `etf_std`: commission `0.00025` floored at **5 CNY per non-zero order**, ETF stamp
duty **0** (the 0.0005 rate in the goal text is a *stock* rate — corrected here), transfer
`1e-05`, one-way slippage `0.0005` (inherited from P1's matrix, **not measured**; open item
§10.3).

---

## 5. Invariants — the tests, not aspirations

1. `NAV = cash + Σ(lots × close_raw)`, and only `ledger/store.py` writes NAV.
2. Every fill's cost recomputed independently from the fee schedule equals the logged cost to
   the cent; a 0-lot order pays 0.
3. No order executes whose **post-rounding** notional is below `5 / (T − slippage − transfer)`
   for its tolerance `T`; the order is suppressed and logged as suppressed, never resized.
4. A sell's proceeds are unavailable to buys until settlement of its instrument class; a T+1
   buy cannot be sold same session.
5. `corp_actions` moves cash on the ex-date with lots constant (dividend) or scales lots with
   cash constant (split); NAV is unchanged by a split.
6. Replaying the same window twice produces a byte-identical ledger hash — the log is
   **tamper-evident** in Crosby-Wallach's sense (consistent with how it was seen in the past).
7. Sleeve combiner fitted-parameter count ≤ 4, asserted at import.
8. No sleeve is silently suppressed: it is tradeable at the declared tolerance or flagged
   `FIXED` and reported in `decision.json`.
9. A rebalance that must both sell and buy is **two-phase**: sells settle on their own date and
   buys are placed only against settled cash. A single-session rotation between sleeves is not
   attempted, because invariant 4 forbids it and pretending otherwise would make the ledger
   replay depend on a fill ordering the exchange does not promise. The gap between the phases is
   part of the measured path, not an assumption.

Hand-computed tests that catch real bugs (these ship as the first test file):
at price 16.00 CNY, desired 4 800 / 5 000 / 5 100 all floor to 4 800 CNY and pay
5.00 + 0.05 + 2.40 = **7.45 CNY = 15.52 bp on the one-way total**, so all three are suppressed
at a 10 bp tolerance (on the commission alone 4 800 looks like 10.42 bp — that is why the gate
must be scored on the total, invariant 3); 6 400 CNY clears 15.1 bp at 12.91 bp; a sell of 150
shares trades 100; a dividend of 0.02/share on 1 000 lots adds 20 CNY and changes no lots; a
suspension yields a stale mark and zero fills.

The gate's arithmetic, solved rather than tabulated: with `var = transfer + stamp + slippage`,
the one-way rate is `5/N + var` below the commission floor and `commission_rate + var` at and
above it, so its infimum is `commission_rate + var = **7.60 bp**`. Hence
`N_min = max(5 / (T - var), ceiling)` and **no order of any size clears T < 7.6 bp**:

| tolerance | 7.6 bp | 10 bp | 15.1 bp | 30 bp | 50 bp | 75 bp |
|---|---|---|---|---|---|---|
| smallest clearing order | 20 000 | 10 204.09 | 5 000 | 2 008.04 | 1 114 | 716 |
| = % of a 50 k / 75 k / 100 k NAV | 40 / 26.7 / 20 | 20.4 / 13.6 / 10.2 | 10 / 6.7 / 5.0 | 4.0 / 2.7 / 2.0 | 2.2 / 1.5 / 1.1 | 1.4 / 1.0 / 0.7 |

Read against the annual-turnover cap. **The earlier reading of this table was wrong** and the
2026-11-04 review says why: turnover ≤ 6/yr does not imply a monthly allowance, still less a
per-sleeve one. It is a pool. At 50 k the pool is 300 000 CNY/yr; at a 15.1 bp tolerance the
smallest executable action is 5 010 CNY, so the pool funds **52 lumps**. The budget never binds
at any NAV in range — the *lump size* does. The constraint is on the resolution of the control,
not on the total spend:

| tolerance | smallest action | 50 k | 75 k | 100 k | lumps funded at 50 k |
|---|---|---|---|---|---|
| 7.6 bp | 20 040 | 40.1 % | 26.7 % | 20.0 % | 13 |
| 10 bp | 10 205 | 20.4 % | 13.6 % | 10.2 % | 26 |
| 15.1 bp | 5 010 | 10.0 % | 6.7 % | 5.0 % | 52 |
| 30 bp | 2 018 | 4.0 % | 2.7 % | 2.0 % | 112 |

**The action set is compared, not assumed.** Fixed-cost theory (Altarovici-Muhle-Karbe-Soner,
arXiv:1306.2802 section 1) is explicit that with a fixed fee "rebalancing takes place by a bulk
trade to the optimal frictionless target", i.e. the non-zero action is *one* state, not three.
So `{0, full}` is the baseline and the half state is the treatment; which one ships is decided
by replaying both through the same executor (build step 6), not by an argument in this
document. The earlier wording — "must therefore emit discrete sleeve states" — overstated a
design choice as a deduction.

**Execution cost is per instrument, not a global 5 bp.** Daily-bar spread estimators fail on
this data (Corwin-Schultz returns 40-72 % negative pairs; Roll is defined on 4 of 11 tradable
codes: `evidence/spread.json`), so the assumption stays and gets a measured lower bound
instead: the exchange quotes these instruments in 0.001 CNY steps, so any crossing trade pays at
least half a tick. On the tradable set the all-in floor (commission 2.5 bp + transfer 0.01 bp +
half tick) is **3.4-7.5 bp**, with 512100 alone at 7.50 bp — effectively at the 7.6 bp infimum
for that code. Market impact stays unmeasured and is reported as such.

---

## 6. E1 — the one experiment that decides the prediction branch

Pre-registered before reading any result. Cheapest check that separates *nonlinearity adds
monthly information* from *the panel is linear at this horizon*.

- **Scope — narrowed to the equity sleeve.** Objections R4 and R6 are right: the panel lives in
  `ashare_v2.duckdb` and only the equity sleeve has a point-in-time bridge from stocks to the
  traded ETF. `index_weight_pit` carries 000300.SH (946 names, 2005-04 … 2026-08), 000905.SH
  (1 917 names) and 000852.SH (2 831 names, from 2014-10) monthly with `available_date`, which
  covers 510300 / 510500 / 512100; there is no bridge for 399006.SZ (159915) and none at all for
  the bond, commodity or overseas sleeves. So E1 predicts **the equity sleeve only**. The other
  three sleeves carry declared static weights, and the ledger records them as declared rather
  than estimated. A claim that the panel prices four sleeves would be unsupported by the input
  data, and stating the narrow version keeps the result interpretable.
- **Design.** Walk-forward, annual refit, 2016–2025 evaluation (10 folds). Features and target
  identical across arms. Arms: (a) `Ridge` on panel z-scored features, (b) `MLP` (2 hidden
  layers, ≤ 64 units, dropout, early stop on a time-ordered validation slice). Both feed the
  same aggregation and the same ≤ 4-parameter combiner, so cost structure cancels inside the
  comparison and the experiment measures forecast quality, which is all it is asked to measure.
- **Target.** Stock-level forward 21-trading-day return; the equity sleeve score is the
  PIT-weight-weighted mean of the model's predictions over the sleeve's index members **plus an
  explicit coverage term** — the share of the ETF's holdings the model can actually predict — so
  a prediction over 40 % of the basket cannot be reported as if it covered the sleeve.
- **Calibration to (mu, sigma, ES).** Not from the model. Per-sleeve mu comes from the model
  score scaled by the historical cross-sectional dispersion of realised returns over the same
  membership; sigma and expected shortfall come from the sleeve's own trailing 24-month return
  series. The model supplies a cross-sectional signal, never a distribution, which is what R4
  asked for and is also what keeps the `≤ 4` parameter count honest.
- **Primary measure.** Net CNY difference between arms at 75 000 CNY after the cost gate and its
  suppressions — the account, not the IC. Reported alongside it at 50 000 and 100 000, because
  the small-change threshold differs by a factor of two across that range.
- **Decision rule (adopt nonlinearity) requires all three:** (i) MLP ≥ ridge in ≥ 70 % of
  folds; (ii) the 6-month moving-block bootstrap 90 % CI of the net-CNY difference excludes
  zero; (iii) the difference ≥ 375 CNY/yr at 75 000 CNY (0.5 % of capital). Failing any one,
  ridge ships and the branch closes with a recorded reason.
- **Secondary, reported whether or not it passes.** IC of each arm; sleeve-deviation share of
  score variance (F-113a8e8d-1); coverage share of the index basket per fold (R4); refit
  CPU-minutes (F-113a8e8d-5).
- **Measurability is a power statement, not a share of months** (R5). Before the verdict, E1
  publishes the minimum detectable effect implied by its own sample: with roughly 120 monthly
  decisions and a measured standard deviation `s` of the monthly net-CNY difference, the 80 %
  power / 5 % two-sided MDE is about `2.8 s / sqrt(120)`. If that MDE exceeds the 375 CNY/yr
  hurdle, the honest verdict is `unmeasurable at this capital` **with the number attached**, and
  no claim about edge is made in either direction. The 50 % threshold this document used before
  is withdrawn: it had no power rationale, and it mixed months with folds.

E1 is a *complexity benchmark*: a null result says nonlinearity is not where the money is at
this sample, and says nothing about learned predictors as a class.

### 6.1 First full E1 run (10 folds, 2016–2025)

Scored population: the 3 634 names that appear in `index_weight_pit`, not the whole market — a
sleeve score is a weighted mean over members, so a never-member name can only dilute the fit.
Artifacts: `evidence/e1-summary.json`, `evidence/e1-report.md`, `evidence/e1-monthly-ic.parquet`,
`evidence/sleeve_scores.parquet`. Wall time 262 s, refit CPU 2.96 min for ten folds — the
refit cost question (F-113a8e8d-5) is answered: cheap.

| year | IC ridge | IC MLP | Δ | MLP months better | λ |
|---|---|---|---|---|---|
| 2016 | 0.0999 | 0.1063 | +0.0064 | 8/12 | 100 |
| 2017 | −0.0528 | −0.0371 | +0.0157 | 7/12 | 0.3 |
| 2018 | 0.0840 | 0.0416 | −0.0423 | 2/12 | 0.3 |
| 2019 | 0.0262 | 0.0321 | +0.0059 | 6/12 | 100 |
| 2020 | 0.0352 | 0.0375 | +0.0023 | 7/12 | 100 |
| 2021 | 0.0890 | 0.1005 | +0.0115 | 6/12 | 100 |
| 2022 | 0.1054 | 0.1296 | +0.0242 | 10/12 | 100 |
| 2023 | 0.1222 | 0.1277 | +0.0055 | 8/12 | 100 |
| 2024 | 0.0356 | 0.0618 | +0.0263 | 9/12 | 100 |
| 2025 | 0.1022 | 0.0980 | −0.0042 | 5/12 | 100 |

Mean fold IC: ridge 0.0647 (sd 0.053), MLP 0.0698 (sd 0.052). Monthly ΔIC: mean +0.0051,
6-month moving-block bootstrap 90% CI **[−0.0045, +0.0137], 120 draws of months, 2 000 resamples**.
Clause (i) passes (MLP better in 8/10 folds, 57% of months); clause (ii) **fails**; clause (iii) is
step 6's net-CNY number and is still open. `adopt_nonlinearity = false`.

What this does and does not say. It says a 14-feature panel with ~2 000 rows per month produces a
mean monthly rank IC near 0.065 out of sample, and that a two-layer MLP does not beat ridge by more
than the fold-to-fold noise can certify. It does not say the panel has no signal — 2017 is the
counter-example that matters: both arms invert (IC −0.053 / −0.037) in the year size and
value reversed, which is the empirical case for a gate that suppresses trading when the score is
weak, and against reading any single fold as the level.

Two secondary readings. Sleeve deviation share (score variance not explained by the common
component): ridge 0.40, MLP 0.32 — so the three sleeves are **not** one factor, and a single
market-timing call on the common component would miss a third to two fifths of the score. Mean
coverage is 0.93 in 2016 and 0.998 from 2020 on, so the coverage term is doing real work only
before the 2019 universe rule change; after that it is a near-constant, which is worth knowing
before it is relied on as a safeguard.

The consequence for the direction: the prediction branch does not carry the thesis. Ridge at the
registered calibration is the arm to carry forward, the band gate has to earn its money on cost
and timing rather than on a linear/nonlinear distinction, and step 6 becomes the only step that
can still move the main metric.

---

## 7. Build order (each step ships something readable alone)

| # | deliverable | why here | est. | state |
|---|---|---|---|---|
| 1 | `data/venue.parquet` + fee/settlement schedule + hashes | every later number depends on it; cannot be chosen after seeing results | 0.5 d | **done** — hash `d6a6e438`, 15 codes, 11 tradable, `newquant/data/freeze.py`, 6 tests |
| 2 | `data/etf_bars.parquet` from akshare `fund_etf_hist_em`, ≥ 2014 | the only unread history available to this project | 0.5–1 d | **done** — 45,197 bars, 2013-01-04 … 2026-11-04, `data/fetch_etf_bars.py`, manifest with per-code coverage |
| 3 | ledger + invariants 1–8 as tests | must be right forever | 1 d | **done** — `newquant/ledger.py` (`LedgerStore`, `Book`), `newquant/order.py`, `tests/test_ledger.py`; I-2 is enforced by re-pricing every fill on load, I-4 by per-class settlement, I-6 by the hash chain |
| 4 | feasibility report from the frozen data (granularity, gate-clearing sizes, executable months) | stands alone as a deliverable | 0.5 d | **done** — `evidence/feasibility-d6a6e438.md` (+ `.json`, `.parquet`), `newquant/eval/feasibility.py`; produced the 7.6 bp floor, the N_min table, and the discreteness requirement |
| 5 | E1: panel features, ridge, MLP, aggregation, walk-forward | decides the prediction branch | 2–3 d | **built and run** — `newquant/panel/{source,features,model,aggregate}.py`, `newquant/eval/e1.py`, 7 panel tests; first full result in §6.1 |
| 6 | three-arm replay: static-annual / vol-conditioned / rule, decomposed cost vs exposure | answers the trade-policy question once | 1 d | **done** — `newquant/replay.py`, `newquant/eval/e2.py`, 51 ledgers, 17 cost cells; result in §7.1: arms unmeasurable, gate non-neutral, overseas sleeve unenterable |
| 6.5 | composition, priced: lot-defined mandate vs the E2 execution vs cash | converts §7.2's either/or into a measured choice before any paper book exists | 0.5 d | **done** — `newquant/eval/e3.py`, `tests/test_e3.py`, `evidence/e3-report.md`; result in §7.3, design v14 adopted at ledger seq 93 |
| 7 | forward paper book, append daily, never rewrite | the only evidence that counts from here | ongoing | **next** — carries the lot-defined mandate from §7.3 |

Steps 1–3 are the settled part and are built first; steps 5–6 depend on nothing subjective
except their preregistered rules. Step 1's measurement changed the design it was meant to
serve: the traded venue is 11 instruments, cash is the residual balance rather than a money
ETF, and the bond sleeve is the two cheap-lot funds. L2 must therefore emit discrete sleeve
states — this is a design change recorded against design v10, not a working assumption.

---

### 7.1 E2 — what the three-arm replay measured (2026-11-04)

Pre-registered as `run_start e2-trade-policy-replay` before any arm-versus-arm number existed.
Engine `newquant/replay.py`, driver `newquant/eval/e2.py`, 14 tests in `tests/test_e2.py`,
artefacts `evidence/e2-report.md` + `e2-summary.json` + `e2-monthly.parquet` and 51 per-run
ledgers in `evidence/e2-ledgers/`. Window 2016-01-04 … 2025-12-31 (2,430 sessions, 120 month-end
decisions) over the frozen venue, 17 cost cells = {50k, 75k, 100k} × {10, 15.1, 30, 50, 75} bp
plus the primary cell under three slippage models. Every cell decides at the month-end close,
sells at the next open, buys at the open after the sale settles, and puts every intent through
the same post-rounding cost gate inside one hash-chained ledger.

**The gate is not a friction on rebalancing — at this capital it is a constraint on the initial
allocation.** At 75,000 and 15.1 bp the smallest admissible order is 3,345 CNY, the median
3,669, the largest 5,066. A sleeve of weight *w* over *k* codes trades only if *w* × NAV / *k*
clears the worst member's floor:

| sleeve | weight | members | slice at 75k | worst member floor | executable |
|---|---|---|---|---|---|
| equity | 45 % | 3 | 11,250 | 5,066 (512100) | yes |
| bond | 35 % | 2 | 13,125 | 3,435 (511380) | yes |
| commodity | 10 % | 2 | 3,750 | 3,669 (159934) | yes, by 81 CNY |
| overseas | 10 % | 3 | 2,500 | 4,436 (159920) | **no** |

The overseas sleeve is unenterable at every NAV in the sweep up to ~120,000: 33 intents over ten
years, zero fills, so the static arm holds **33.2 % of the account in cash at entry** and 10.5 %
at the end, with its equity weight drifting to 38 % of NAV against a 45 % target. The arm the
design calls "static-annual" is therefore not a policy on this venue; it is the mandate plus an
execution failure. F-113a8e8d-6 ("does a 2,500–3,000 CNY minimum order freeze marginal
rebalancing?") is answered from the other end than it was asked: the minimum order is not a drag
on drift, it decides which sleeves exist at all. 90.2 % of all sized intents sit below the floor.

**The trade mechanism dominates the state conditioning.** Loosening the gate alone, with no
change to any arm, moves the static arm's terminal wealth from 94,979 to 133,645 (+41 %):

| tolerance | static fills | static end NAV | Δ vol | Δ rule |
|---|---|---|---|---|
| 10 bp | 7 | 94,979 | +915 | −26 |
| 15.1 bp | 10 | 105,810 | +417 | +259 |
| 30 bp | 32 | 133,645 | −177 | −201 |
| 50 bp | 39 | 131,307 | −451 | −357 |
| 75 bp | 43 | 131,933 | −624 | −241 |

The conditioned arms are worth more than the static arm exactly where the static arm is
crippled, and less wherever it can trade. At 10 bp the *entry* itself is only 7 fills of 10, so
a third of the mandate never leaves cash; at 30 bp it trades 32 times and gains 27,835 on the
tighter-gate arm. One policy number, no strategy content, a 38,666 CNY spread.

**Neither conditioned arm is measurable at this capital.** Primary cell, 75,000, 15.1 bp,
measured slippage: vol +417 CNY/yr (90 % CI −716 … +1,666, MDE 1,750); rule +259 (CI −4 … +580,
MDE 545). Three independent pre-registered grounds fail together — the interval covers zero, the
design's minimum detectable effect is 4.7× the 375 CNY/yr threshold that would have to be
cleared, and the sign reverses across the sweep. The vol arm's advantage is two episodes (2018
+4,385, 2024 +4,515 against 2023 −2,535) and it carries the *worse* drawdown (−22.2 % against
−16.3 %), which is backwards for a volatility conditioner. At 50,000 the same comparison is +58
CNY/yr with MDE 793; at 100,000 it is +429 with MDE 2,049. The rule arm's only positive cell at
15.1 bp is the middle one (+259 at 75,000 against −18 at 50,000 and −5 at 100,000), so the sign of
its advantage tracks the account size rather than the rule. The trade-policy question is closed at
`unmeasurable at this capital`, and `band-rule-demoted-scoped` (seq 34) is the standing reading.

**Accounting that would have decided the answer by itself.** Dividends credited as cash on the
ex-date come to 9,390 CNY for the static arm — 30.5 % of its 30,810 CNY total gain, or ~1.25 pp
of annual return (upper bound, no reinvestment). Without that treatment the comparison whose
whole margin is 0.5 pp would have been wrong by 2.5× its own threshold. Unit changes are lot
ratios with the truncated fraction paid as cash, so NAV is continuous (511220 10:1 on
2023-01-16, 513100 5:1, 513500 2:1, 512100 0.365708); the residual totals 211 CNY over ten years
and would have been a silent 214 CNY loss at 512100's 76-lot position without it.

**What this changes in the design (design v13 candidate).** The equal-weight-within-sleeve rule
is wrong at this capital: a member's slice must clear its own floor, or the sleeve must drop to
fewer members, or the tolerance must rise. Concretely, at 75,000 the overseas sleeve needs one
code, not three, and commodity is one lot away from the same failure. Any future arm comparison
must also be run at a tolerance where the *baseline* trades, or it measures the gate instead of
the arm — the sweep here is the cheapest version of that control and it already reverses the
answer.


## 7.2 What the composition probe measured (2026-11-04)

§7.1 concluded that a member's slice, not the annual budget, decides which sleeves exist, and
left as a design candidate a rule where each member's slice clears its own floor. Before writing
a replay for that rule, two throw-away scripts (`evidence/probe-composition/probe_table.py`,
`probe_realised.py`; outputs `table.json`, `realised.txt`) asked the smaller question: at what
member count `k` can each sleeve actually be *entered*, and what weight does the venue then
express? 42 seconds, 0.7 CPU-minutes, four reference dates.

The answer is that the floor was the wrong number. A slice must clear the cost floor *and* one
board lot at the era's price, and for bonds those differ by a factor of three:

| sleeve | code | `min_notional` 15.1 bp | one lot 2016 | one lot 2020 | one lot 2023+ |
|---|---|---|---|---|---|
| bond | 511220 | 3,345.02 | **10,000** | **9,823** | 988 |
| bond | 511380 | 3,435.36 | unlisted | 998 | 1,128 |
| equity | 510300 | 3,649.01 | 354 | 378 | 381 |
| equity | 510500 | 3,523.18 | 719 | 569 | 610 |
| equity | 512100 | 5,066.23 | unlisted | 74 | 264 |
| commodity | 518880 / 159934 | 3,668.88 / 3,669.46 | 225 / 223 | 368 / 365 | 436 / 971 |
| overseas | 513100 / 513500 / 159920 | 4,026.63 / 4,102.98 / 4,436.00 | 159 / 123 / 108 | 318 / 181 / 134 | 103 / 140 / 106 |

Largest feasible member count with `slice = w x NAV / k >= max(floor, one lot)`: at 50,000
equity 3, bond **1**, commodity 1, overseas 1 (6 instruments, inside the cap); at 75,000
3/2/2/1 = 8; at 100,000 3/2/2/2 = 9. So a composition exists, and the cap rather than the floor
is what binds above 50,000 — the opposite of what §7.1 assumed.

What it then expresses, buying whole lots against the target at entry:

| NAV | era | bond target | bond bought | bond gap | capital deployed | cash |
|---|---|---|---|---|---|---|
| 50,000 | 2016 | 35.0 % | 20.0 % | **-15.0 pp** | 83.3 % | 16.7 % |
| 50,000 | 2020 | 35.0 % | 19.6 % | -15.4 pp | 82.3 % | 17.7 % |
| 50,000 | 2023+ | 35.0 % | 33.6 % | -1.4 pp | 97.1 % | 2.9 % |
| 75,000 | 2016 | 35.0 % | 26.7 % | -8.3 pp | 90.8 % | 9.2 % |
| 100,000 | 2016 | 35.0 % | 30.0 % | -5.0 pp | 94.3 % | 5.7 % |

Equity lands within 1.5 pp at every NAV, commodity and overseas within 0.5 pp; bonds alone are
short, because every bond and money-market ETF on this venue quotes near par (100.0-141.4 CNY),
so one lot is 10,000-14,135 CNY against a 17,500 CNY sleeve at 50,000. The deficit is structural
for 2016-2022 and disappears when 511220 splits 10:1 in January 2023 and its lot becomes 988 CNY.

Four things follow, and they are the reason this section exists:

1. **The entry condition changes.** v13's requirement was `slice >= min_notional(...)`. It has to
   be `slice >= max(min_notional(...), one board lot at the era's price)`. A slice can clear the
   cost gate and still be unbuyable, which is a different failure from the one §7.1 named.
2. **The mandate stops being a weight vector below about 120,000 CNY.** Either the bond sleeve is
   specified in lots — the target weight becomes endogenous, `lots x 100 x price / NAV` — or the
   capital floor rises to the point where `floor(0.35 x NAV / 10,000) x 10,000` lands within 2 pp
   of target, which first happens near 120,000. There is no third option on the frozen venue:
   511010, 511260, 511880 and 511990 all cost more per lot (14,135 / 13,578 / 10,093 / 9,999).
3. **E2's 50,000 reading has to be derated.** The static arm there entered with 37.4 % cash
   (`cash_weight_first` 0.4090) and held three codes: equity 41.96 %, bond 20.65 %, commodity 0 %,
   overseas 0 %. A first draft of this section wrote "44 / 20 / 10 / 10 with 16.7 % idle cash",
   which is the *probe's hypothetical* portfolio, not what E2 executed — corrected 2026-11-04 in
   §7.3 after the entry-day fills were rebuilt from the ledger. Nothing in §7.1 is withdrawn — the
   gate still decided which sleeves existed — but the executed weights were not the ones the
   mandate names, and they were further from it than the probe assumed.
4. **The acceptance criterion I pre-registered in idea v6 was mis-specified.** It asked whether
   the *equity* weight stayed within 2 pp, and this probe passes that test at -1.5 pp while bonds
   sit 15 pp off. The measure has to be the worst sleeve. That pre-registration is recorded as
   wrong rather than quietly amended, and the next version inherits the corrected measure.

A replay of the composition is therefore not the next step: it would price a portfolio whose bond
sleeve is short by 15 pp of its own mandate, and the deficit would be attributed to the
composition rule. The table above is the cheap answer that removes that confound first.


## 7.3 E3 — the composition, priced in CNY (2026-11-04)

§7.2 ended with a recommendation not to replay the composition yet. It was right about the
confound and wrong about the order: once the bond deficit has a rule, the deficit *is* the thing
to price, and leaving it unmeasured is what made v13 look acceptable. E3 (`newquant/eval/e3.py`,
`evidence/e3-report.md`, run `run-e3c00001-50k0-4c01-9a00-000000000001`, 30.6 s, 6 replays)
prices four arms on the same cell — 50,000 CNY, 15.1 bp gate, measured slippage,
2016-01-04 … 2025-12-31.

**Control first.** The `static` arm reproduces E2's `nav50000_tol15.1_measured` cell exactly:
NAV 62,163.64, 6 fills, ledger head `db6a4f19`. Without that, nothing below means anything.

| arm | NAV end | CAGR | vol | max DD | cost bp/yr | fills | intents | TE |
|---|---|---|---|---|---|---|---|---|
| `static` (= E2 execution) | 62,163.64 | 2.20 % | 9.40 % | -19.17 % | 0.75 | 6 | 102 | 33.17 % |
| `lots` (adopted) | **85,111.30** | 5.46 % | 8.63 % | -12.27 % | 1.67 | 14 | 65 | 16.30 % |
| `lots_deploy` (rejected) | 91,610.12 | 6.24 % | 8.99 % | -13.69 % | 1.86 | 15 | 67 | 22.49 % |
| `cash` | 50,000.00 | 0.00 % | 0.00 % | 0.00 % | 0.00 | 0 | 0 | 0.00 % |

Entry day, rebuilt from the fills rather than read at the first month end (January 2016 was an
equity crash, which flatters any arm that failed to buy equity):

| arm | invested | cash | equity | bond | commodity | overseas | codes |
|---|---|---|---|---|---|---|---|
| `static` | 62.61 % | 37.39 % | 41.96 % | 20.65 % | 0.00 % | 0.00 % | 3 |
| `lots` | 80.43 % | 19.57 % | 39.72 % | 20.63 % | 10.22 % | 9.86 % | 5 |
| `lots_deploy` | 98.07 % | 1.93 % | 51.98 % | 20.83 % | 12.66 % | 12.61 % | 5 |

The idle cash, first-order (the cash held missed the mandate's own return for the next month,
compounded): `static` 11,252 CNY (254.2 bp of NAV0 per year), `lots` 6,297 (142.0),
`lots_deploy` 3,010 (70.3), `cash` 48,948. That is the size of the object design v13 did not have.

Paired differences, 6-month moving-block bootstrap, 2,000 draws, seed 20261104:

| pair | CNY/yr | 90 % interval | MDE | reading |
|---|---|---|---|---|
| `lots - static` | +1,542.8 | [857.8, 2,212.6] | 1,393 | measurable |
| `lots_deploy - static` | +1,930.0 | [1,150.1, 2,783.6] | 1,667 | measurable |
| `lots_deploy - lots` | +387.2 | [-71.6, 973.7] | 933 | **unmeasurable at this capital** |
| `lots - cash` | +2,851.2 | [1,264.1, 5,026.6] | 3,819 | measurable |
| `lots_deploy - cash` | +3,238.4 | [1,768.4, 5,494.0] | 3,978 | measurable |

**Design v14 adopts `lots` with the residual in cash** (ledger seq 93). Both lot arms clear the
control; they do not separate from each other, so the decision does not go to the larger point
estimate. `lots_deploy` converts the residual into a 52.0 % entry equity weight and 12.7 % in each
small sleeve, and an unmeasured +387 CNY/yr does not pay for that. This is the same test that
closed the trade policy in seq 78, applied to a result I would have preferred.

Four further findings:

1. **The `aimed` / `realised` distinction is load-bearing.** `aimed` is the decision target after
   whole lots; `realised` is the same sleeve a month later and contains its own price drift. At
   120,000 the bond sleeve quantises to 0.56 pp at entry — better than §7.2's 2 pp — while its
   `realised` gap at the last decision is 9.1 pp. Reading the second as quantisation would send
   the mandate to a capital floor it does not need; §7.2's -15 pp deficit is an `aimed`-class
   statement and stands.
2. **The capital floor is not a permanent fix.** 511220 trades at 100.00 on 2016-01-04 and at
   10.21 in 2025 after the 10:1 split, with 511380 at 13.66, so the same 120,000 buys different
   fidelity in different eras. A floor is a measurement about prices, and prices move.
3. **The probe over-counted instruments.** At 2016-01-04 the expressible tree is 5 codes, not 6:
   `probe_table.py` skipped a member with no price (`if px is None: continue`) instead of dropping
   it, so it counted 512100, which lists 2016-11-04. Bond, commodity and overseas agree; the
   probe's 50k total and any derived "6 codes" sentence are corrected at ledger seq 90, and
   `newquant.replay.lot_composition` is now the single owner of the rule.
4. **Measured, not assumed: the redeploy rule cannot be a percentage threshold.** The first
   implementation asked whether a sleeve expressed ≥ 99 % of its target; at 2016-01-04 commodity
   sat at 0.0990 against the threshold 0.0990 and overseas at 0.0988, so a 0.0002 difference sent
   a 10 % sleeve to 23.8 %. The rule that replaced it has no free parameter: `gap = target −
   expressed`, and any sleeve holding at least half the total gap is "lot-bound" and keeps its own
   expression while the rest absorb the residual pro rata.

The evidence is `evidence/e3-report.md` (8 sections), `e3-summary.json` (the machine copy — every
number above is read from it, not from the markdown), `e3-monthly.parquet` (120 rows per arm with
`aimed_*` / `realised_*` / `members_*` per sleeve), and six ledgers under `e3-ledgers/`. Tests:
`tests/test_e3.py`, 21 cases pinning the floor, the `k` rule, floor-rounding, the redeploy
invariants, the decision rule and the control check; the whole suite is 101 passing.


## 8. Decisions this document asks the ledger to adopt

- `direction-v4`: the direction above, replacing v3's decoupled-estimation statement with the
  panel-layer estimation target and the ≤ 4-parameter interface.
- `design-v7`: this architecture, superseding design v6 (trains at the panel layer, ceiling as
  construction + rejection rule, block bootstrap, executable-month contract, corp-action input).
- `band-line-closed`: retire the four remaining `F-60b5f78a-*` objections with the band-rule
  demotion plus the ETF stamp-duty correction; the band rule survives only as a sensitivity.
- `design-v12`: this document after the 2026-11-04 review — action set compared rather than
  deduced, two-phase execution (I-9), E1 narrowed to the equity sleeve with a power-based
  measurability rule, per-instrument tick floors recorded as the executed-cost bound.
- `composition-mandate-v14-lot-defined`: design v14's mandate — each sleeve's member count is the
  largest whose per-member slice clears `max(that code's gate, one board lot)`, the target weight
  becomes what whole lots are worth, and the residual stays in cash (ledger seq 93). Carries the
  entry condition from `composition-entry-condition-v14` (seq 86, retained) and replaces its
  either/or about a 120,000 capital floor with a measurement. Adopted on `lots - static`
  +1,542.8 CNY/yr, 90 % interval [857.8, 2,212.6]; `lots_deploy` rejected because its incremental
  +387.2 CNY/yr does not separate from zero.
- `lotting-prior-art-dispositions`: the four verdicts of the lotting search (2026-11-04) —
  Mansini & Speranza's minimum-transaction-lot formulation **adapted** (concept, not MILP: at
  50,000 the feasible set is six instruments and there is no objective to optimise), MSCI Barra's
  post-optimisation roundlotting **adopted as the falsification target** (our rule is exactly that
  object, and E3 is what prices it rather than assuming it away), Chang et al. and
  Bertsimas–Cory-Wright **rejected** (cardinality is declared by the mandate; there is no μ/Σ to
  sparsify), and no library adopted (riskfolio-lib / cvxpy / PyPortfolioOpt rejected: Decimal
  accounting to the cent is worth more than a float MIQP, and no new dependency).
- `prior-art-dispositions`: the five verdicts of 11 and what was adopted from each (Baule's
  cost decomposition and falsification target; BSCV's parameter-count defence; Leippold's
  proportional-cost benchmark for the panel layer; Altarovici's binary action baseline;
  Crosby-Wallach's vocabulary), and the three rejections (DVC's hash policy, the three-state
  grid as a *deduction*, GP's smaller-investor aside as support).

---

## 9. Kill criteria (unchanged where still valid)

- Static arm structural drag > 0.5 % of capital/yr at 50 k → reduce instrument count, not drag.
- Band/vol arm cannot make most sleeves tradeable at 50 k → trade policy closed at annual-only
  until capital changes 5×.
- Realised risk beyond mandate in > 10 % of sessions → cash is not carrying the fine
  adjustment; fall back to a coarse 20–28 % block with reported tracking error.
- Static arm indistinguishable from buy-and-hold of one broad ETF over the paper book →
  allocation layer earned nothing and is replaced by the simpler thing.
- E1 null under its three-part rule → prediction branch closed, project proceeds as account
  infrastructure with source 1 or 3.

---

## 10. Open items (with the measurement that closes each)

1. **Measured one-way spread — closed as a bound, open as a number.** Daily-bar estimators
   cannot price these instruments: Corwin-Schultz returns 40–72 % negative two-day pairs and
   Roll is identified on 4 of the 11 tradable codes (`evidence/spread.json`). What the data does
   support is the exchange tick: 0.001 CNY, so half a tick is 0.04–4.90 bp depending on price,
   and the all-in floor including commission and transfer is **3.4–7.5 bp** on the tradable set.
   The inherited 5 bp therefore survives inside that band, and the 7.6 bp infimum holds for 512100
   almost exactly. Market impact is still unmeasured and is now labelled as the remaining
   assumption rather than a measured input.
2. **Is the bond sleeve a measured stabiliser or only labelled one?** Close it with realised
   vol and correlation of the sleeve series against the equity sleeve — the granularity census
   is by class, not risk.
3. **Bond/money-market ETFs quote at par — structural or incidental?** The 2026-11 census is a
   snapshot; new listings reset the constraint. Re-measure after step 2's bar pull.
4. **Does the ≤ 4-parameter combiner leave enough freedom to express the panel score?**
   If the score's information lives in interactions, a 4-parameter linear combiner throws it
   away and E1 would understate any model. Guard: E1 also fits the combiner on a 4-feature
   basis chosen *before* seeing results (expected return, expected vol, expected shortfall,
   deviation-from-common).
5. **T+0 vs T+1 by class** must be verified against the live venue table for the five chosen
   instruments; the table above is the design assumption, not a measured fact.
6. **Is the 14 pp bond shortfall a drag or a stabiliser?** (§7.3) The lot-defined mandate holds
   20.6 % bonds where it declares 35 %, for the whole 2016-2022 sub-period, and the +1,542.8
   CNY/yr comparison is entangled with the commodity and overseas sleeves existing at all. Close
   it by decomposing the E3 monthly series into sleeve contributions — one replay per sleeve
   zeroed, same window, same gate — not by re-running the same comparison with a different story
   attached to it.
7. **Does the redeploy gain ever become measurable?** `lots_deploy - lots` is +387.2 CNY/yr with
   an MDE of 933 at 50,000. The MDE scales with the standard deviation of the monthly difference,
   not with NAV, so more capital does not buy resolution by itself; a longer window or a
   lower-variance residual does. Recorded as unmeasured, not as zero — if it is adopted later it
   must be adopted by a measurement, not by the fact that it looked better once.

---

## 11. Prior art, and what the review changed (2026-11-04)

Five separable claims were searched in their general form, not in this project's wording; the
full audit trail (39 queries, engines used, what failed) is `evidence/prior-art-2026-11-04.md`.
Verdict vocabulary is the one the method fixes: `核心已有` / `部分已有` / `尚未检出对应工作` /
`证据不足`.

| # | Claim | Verdict | Disposition |
|---|---|---|---|
| C1 | the executable order is the unit of decision; estimation breadth decoupled from holding breadth | 部分已有 | **adapt** — Baule (2010) owns the mechanism and the wealth→`n*` map; only the *empty feasible set* is ours, and it moves to C4 |
| C2 | panel (mu, sigma, ES) → ≤4-parameter combiner; NN only as a comparison arm | 部分已有 | **adapt** — justify the split by parameter count alone, not as architecture, because BSCV argue the opposite |
| C3 | net CNY under turnover ≤ 6 with a constructed drawdown ceiling; discrete action grid | 部分已有 | **adapt + change of baseline** — `{0, full}` is the theoretical default, the half state is a treatment |
| C4 | feasibility as a first-class output: minimum executable order, cleared-cell share, executable months | 部分已有 | **adapt and concentrate here** — the metric is the only new object in the five |
| C5 | post-rounding cost gate + hash-chained ledger with per-class settlement | 部分已有 | **vocabulary only** — textbook engineering; drop it from the contribution list |

**Adopted, with the reason each one changes this document.**

- *Baule (2010), OR Spectrum 32:61–76* — transaction-cost versus **risk-cost** decomposition, so
  "this order is inadmissible" can be priced against "hold one more name and accept the risk
  cost". Also his Table 2, used as a falsification target: the published optimum at this capital
  is `n* ≈ 2–3` names, and this design runs four sleeves plus cash. Either the fourth clears the
  gate or the sleeve count falls; measured, at 15.1 bp and 50 k, the smallest executable action
  is 10.0 % of NAV, which is the number that decides it. Licensed CC-BY-NC, no code released,
  nothing ported.
- *Brandt, Santa-Clara & Valkanov (2009), RFS 22(9):3411* — the ≤4-parameter rule is their
  parametric portfolio policy, and they reject layering explicitly. The split survives only with
  the parameter-count argument (about 900 basket-months at 50 observations per parameter ≈ 18
  parameters at the holding layer), which is now stated as a trade-off instead of an advance.
- *Leippold, Wang & Zhou (2022), JFE 145(2):64–82 §4.4* — 2–3 bp retail commission, 10 bp
  unilateral stamp tax on sellers, ~10 bp round-trip slippage, "25 bps might be a reasonable
  estimate" in normal times. These are **proportional** numbers with no per-order floor, so they
  are adopted as the panel layer's cost benchmark and explicitly not as support for a 50 k
  order-level claim.
- *Altarovici, Muhle-Karbe & Soner, arXiv:1306.2802 §1* — "since trades of all sizes are now
  penalized equally, rebalancing takes place by a bulk trade to the optimal frictionless target".
  This is why the action set is now compared (`{0, full}` versus three states) rather than
  deduced, and it also explains why the earlier "must emit discrete states" sentence was wrong:
  it derived a design choice from a cost formula that does not imply it.
- *Altarovici, Reppen & Soner (2017), SIAM J. Control Optim. 55(3):1673–1710 §5.7* —
  "at low wealth levels, fixed transaction costs are the predominant cost consideration". The
  wealth dependence is published, so this project's premise is a known branch, not a discovery.
- *Crosby & Wallach (2009), USENIX Security* — the words **tamper-evident** and *consistent with
  how it was seen in the past* are theirs; I-6 now uses them. The Merkle-tree refinement solves
  a problem a 40-order-per-year ledger will not have, so only the vocabulary is adopted.

**Rejected, with the reason recorded.**

- *DVC* (`treeverse/dvc`, Apache-2.0, `main`) — read at source, not from the abstract:
  `dvc/repo/index.py:123` silently drops a hash whose algorithm differs
  (`hash_info=ohi if (ohi and ohi.name == hash_name) else None`) and `:199-201` then refreshes
  it. That is exactly the failure mode `newquant/ledger.py:96` raises on
  (`LedgerError("hash mismatch (record edited)")`). The licence would permit reuse; the policy
  must not be imported.
- *The three-state grid as a deduction* — see C3. It may still win on merit in step 6; it does
  not follow from the floor.
- *Garleanu-Pedersen as support* — after eq. (10) they state the opposite reading ("a larger
  absolute risk aversion can also be viewed as a smaller investor, for whom transaction costs
  play a smaller role, and who therefore trades closer to her aim"). True for quadratic cost,
  false with a per-order floor; the doc now says which branch applies.

**The contribution, in one sentence.** At a 5 CNY commission floor with a 100-share lot, the
fraction of (month × instrument) decisions that are executable is 0.1 % at 50 k and 99.7 % at
100 k, and the smallest executable action is 10.0 % / 6.7 % / 5.0 % of NAV at 50 k / 75 k /
100 k on a 15.1 bp tolerance — which makes *not measurable at this capital* a verdict prior work
does not report, and makes the control discrete rather than a weight vector. Everything else in
C1–C5 is scaffolding around that sentence.

**Single point of failure, recorded.** The 5 CNY minimum is regulatory, not incidental: brokers
are barred from waiving it (免5 prohibition, 财联社 2026-10-26, https://www.cls.cn/detail/2160172).
If the rule changes, the whole construction changes with it, and the measured granularity table
is the first thing that becomes stale.

**Still unverified, and therefore not used.** Constantinides (1986), Davis & Norman (1990),
Brennan (1975), Grossman & Zhou (1993), Basak & Shapiro (2001), Jobst et al. (2001 — PDF
unreadable), Kellerer et al. (2000 — abstract only): all cited only as pointers, none load-bearing.
Highest priority for a later read: "Portfolio-optimization models for small investors", *MMOR*
(2012), DOI 10.1007/s00186-012-0408-3. Not searched at all: Chinese retail ETF rotation / dual
momentum, and the power of asset-pricing tests ("lucky factors") — the second is the natural
home for the MDE rule above.
