# New project: direction, architecture and framework

Status: discussion document, superseded for direction and architecture by
`D:/newquant/docs/direction-architecture.md` (direction v4, design v7). Keep this file for its
measured numbers and the review history; do not read §6 as current. Ledger at `D:\newquant\.quant\ledger.jsonl`
(idea `etf-implementable-frontier`, v2, design v5, review outcome **blocked**).
Evidence bundle: `D:\newquant\evidence\prior-project-evidence.md` plus three measured CSVs.

---

## 1. What the two old projects actually establish

Both were competent measurement machines. Neither produced a net account return, and the reason is
arithmetic rather than subtle.

**P1 `D:\minequant\AlphaGPT`** searched A-share formula factors against a scalar reward. Its own
adjudications say it failed on its own terms:

- `data/p11_searcher_comparison/adjudication.json`: `negative_no_admissible_formula`, admissible
  arms `[]`. Only one of twelve arms (TPE seed 42) passed all four gates.
- `data/protocol_result.json`: 5 folds 2021-2025, 55 candidates, 6 with positive excess, median
  excess **-12.94 %**, none with both positive excess and Sharpe above 1.
- `data/sim_portfolio_state.json`: 2,822 sessions, 28,179 trades, 100,000 → **5,946.37 (-94.05 %)**.
- `reports/project-assessment-20261018T040526Z.json`: 270 shortlist rows, median fee **9.9 % of
  initial capital**, and validation reward versus realised net return at **Spearman -0.043**.
- `data/holdout_registry.json` does not exist although the README cites it; the experiment ledger
  has ten rows, all `selfcheck:noise`.

**P2 `D:\进益资本杯`** built minute-level models against an official 30-minute forward VWAP label and
scored 0.23993 on the platform. Its gate table, which I read directly from
`runs/a-gate/20261027T050733Z/day-set-result.json`, is the sharpest artefact either project produced:

| arm | rankIC | gross spread | turnover | cost @5bp | net | breakeven |
|---|---|---|---|---|---|---|
| nine-model reference | 0.0707 | 5.30 bp | 1.102 | 11.02 bp | **-5.73 bp** | 2.40 bp |
| ridge baseline | 0.0070 | 0.19 bp | 0.003 | 0.03 bp | **+0.17 bp** | 29.94 bp |
| shuffled control | 0.0030 | 0.30 bp | 1.603 | 16.03 bp | -15.73 bp | 0.09 bp |
| sign-flipped control | -0.0707 | -5.30 bp | 1.103 | 11.03 bp | -16.32 bp | -2.40 bp |

The sign-flipped arm mirrors the reference exactly, which confirms the arithmetic. The reading is
uncomfortable: **a tenfold gap in IC points the wrong way versus money.** The only net-positive arm
is the one that barely trades. P2 never had fees, T+1, tick size or position limits anywhere in its
pipeline, and it has no fills or simulated trades at all — its performance is notional.

**The corrected lesson.** Neither project lacked cost accounting. P2 had `single_side_rate` and
`breakeven_single_side_rate` in `evaluation.py:15,301`; P1 had `ExecutionCostModel` in
`ashare_execution.py:133-146` and a complete `fee_matrix.json`. What both lacked was **a gate on it**:
P1 selected on reward and P2 selected on rank IC, and both objectives are documented as uncorrelated
with money. So the transferable judgement is not "they forgot costs". It is:

> Both projects measured cost. Neither let cost decide anything. Any new line must make cost a
> constraint inside selection, not a report written afterwards.

---

## 2. Can they be integrated — and why that is the wrong question

Integration is possible, cheap, and not the win. The reusable parts are narrow and real:

| take | from | why |
|---|---|---|
| fee and lot arithmetic | `D:\minequant\AlphaGPT\ashare_execution.py:22-35,133-146` | floors the delta to whole lots, floors commission per non-zero order, stamps sells only. Port it; do not rewrite it. |
| fee parameters | `data/fee_matrix.json` | commission 0.00025, min 5.0 CNY, transfer 1e-05, slippage 0.0005. Stamp 0.0005 **does not apply to ETFs** — that is a stock rate. |
| preregistration + gate discipline | `D:\进益资本杯\src\jinyiquant\protocol.py`, `comparison.py` | hash-chained preregistration, paired bootstrap, `decision.json`. This is the governance layer worth inheriting. |
| report schema | `evaluation.py`, `daily.csv`, `decision.json` | reuse rather than invent. |
| causal feature discipline | `book_features.py` | the truncation-perturbation proof is a good pattern; irrelevant to a daily-frequency project, but the habit is not. |
| A-share PIT stock panel | `ashare_v2.duckdb` | 12,008,787 rows, 20140102-20261015, 5,820 codes. Useful later if the line ever returns to stock selection. |

What must not be inherited: P1's reward-objective search loop, P2's turnover profile, either
project's habit of declaring a window "out of sample" after using the same years many times, and
P2's 1.10-per-day turnover, which consumes the entire gross alpha before any fee is charged.

The real boundary: **integration would rebuild the machinery that both projects already proved does
not earn money.** The new line needs the opposite of more machinery. It needs a smaller account
loop, and one honest answer about where a return is supposed to come from.

---

## 3. The one thing neither project ever measured: the account

No ETF panel exists in either project — `grep -i etf` returns 3 incidental hits in P1 and 1 in P2,
and `ashare_v2.duckdb` has a 5,542-row `stocks` table and no ETF table. That history is **unread**,
which is a weaker thing than out-of-sample but is genuinely fresher than the 2021-2026 window both
projects have worn out.

Measured over the whole live universe (2026-11 spot, one board lot of 100 shares as a share of a
50,000 CNY account):

| sleeve | n | median unit price | lot as % of 50k | at ≤5 % |
|---|---|---|---|---|
| commodity | 45 | 0.90 | 0.2 % | 45 / 45 |
| equity | 1,351 | 0.99 | 0.2 % | 1,350 / 1,351 |
| overseas | 242 | 0.93 | 0.2 % | 242 / 242 |
| cash-like (money market) | 26 | 100.00 | **20.0 %** | **0 / 26** |
| bond | 52 | 102.84 | **20.6 %** | **3 / 52** |

Return-seeking sleeves are effectively continuous at this capital: 1,637 of 1,638 instruments clear
a 5 % granularity bar. The stabilising sleeves are not. All 26 money-market ETFs quote at par, so a
lot is 20.0 % of 50k, 13.3 % of 75k and 10.0 % of 100k. Of 52 bond ETFs only three fall under 5 %,
and **all three are anti-stabilisers**:

| code | name | price | % of 50k | why it does not stabilise |
|---|---|---|---|---|
| 511220 | 城投债ETF海富通 | 10.441 | 2.1 % | LGFV credit risk, not a rate hedge |
| 511180 | 可转债ETF海富通 | 11.621 | 2.3 % | convertible = equity beta in disguise |
| 511380 | 可转债ETF博时 | 12.539 | 2.5 % | same |

Every genuine stabiliser is par-quoted and coarse: 511360 at 22.8 %, 511260 at 27.1 %, 511010 at
28.2 %, with 511520 政金债, 511200 信用债 and 511110 公司债 all in the 100-141 CNY band.

**Within fixed income, granularity and stability are anti-correlated at this capital.** The only
finely divisible stabiliser is uninvested cash, which has no lot constraint at all. So the defensible
statement is narrower than the one a reviewer rejected earlier: a lot-size census does not prove a
risk property, and "stabilising" here still means instrument class plus the price band, not measured
volatility. That measurement is owed.

---

## 4. What the reviews changed

Three rounds of `quant_review`, all recorded in the ledger. Round three was blocked on four high
objections, so this is not a passed proposal.

Round 1 (direction, 2 reviewers) returned `mixed` / `pursue` and blocked on six objections. It killed
three of my claims outright: the lot-precision assumption ("within 5 % of target") is false at the
boundary; inverse-volatility weights are not portfolio volatility targeting; and a two-arm test
confounds momentum, weighting and rebalance frequency so it can attribute nothing.

Round 2 (cross) returned `invest` / `explore` and produced four corrections, of which two were
arithmetic errors I had shipped:

- **The fee-floor test must run on the post-rounding notional.** At a 16 CNY price one lot is
  1,600 CNY; a 5,100 CNY order floors to 4,800 and pays 5 CNY = **10.42 bp**, passing a pre-rounding
  test while violating the declared tolerance. 4,800, 5,000 and 5,100 all floor to 4,800; 6,400 is
  the first size that clears the gate.
- **A 10 bp tolerance is commission-only.** Adding 5 bp slippage and 0.1 bp transfer makes it 15.1 bp
  at the 5,000 CNY boundary.
- I also dropped a "3× horizon change" claim: at 5 bp the breakeven turnover is 0.53, a 2.08×
  reduction, and horizon changes move gross spread too. The only defensible statement was that
  cost-adjusted implementability has to enter selection.

Round 3 (direction at v2, 2 reviewers) returned `mixed` / `pursue` again and blocked on four highs.
Both reviewers independently found the same two arithmetic problems, which is what makes them
credible:

- **R2, the ceiling.** Commission-floor avoidance is bounded at 5 × 4 quarters × 12 instruments =
  **240 CNY/yr = 0.32 % of 75,000.** My hurdle was 375 CNY. The rationale could not pay for itself.
- **R5, the livelock.** At 50k with ten sleeves the average sleeve is 5,000 CNY. A 15.1 bp tolerance
  demands a 5,000 CNY order — the entire sleeve. No partial drift can ever clear the gate, so the
  band rule degenerates into a hold.

Two medium findings were also correct and embarrassing: my design said "stamp duty 0.0005 on sells"
in the goal while the experiment assumed ETF exemption (P1's rate was a *stock* rate), and sizing
lots on raw prices while deriving NAV from positions and cash alone silently loses dividends and
splits without a corporate-action feed.

---

## 5. The number that decides the project

I extended R2 from the commission floor to total cost, because the floor alone understates the prize:

| account | sleeve | cost of one full-sleeve order | 40 orders/yr | as % of capital |
|---|---|---|---|---|
| 50k | 5,000 | 7.55 CNY (15.0 bp) | 302 CNY | 0.60 % |
| 75k | 7,500 | 8.82 CNY (11.8 bp) | 353 CNY | 0.47 % |
| 100k | 10,000 | 10.10 CNY (10.1 bp) | 404 CNY | 0.40 % |

**353 CNY a year at 75k is the entire trading budget any policy can compete for.** A band rule can
capture only the fraction of that it actually avoids — realistically a third to a half. A hurdle set
at 0.5 % (375 CNY) therefore sits *above the total addressable saving*, which means the experiment I
designed could not have succeeded on its own terms.

The tolerance is not a free parameter either:

| one-way tolerance | minimum admissible order | as % of 50k |
|---|---|---|
| 10 bp | 10,204 CNY | 20.4 % |
| 15.1 bp | 5,000 CNY | 10.0 % |
| 30 bp | 2,008 CNY | 4.0 % |
| 50 bp | 1,114 CNY | 2.2 % |

Any rule loose enough to trade at 50k is implicitly accepting 30-50 bp per order — a worse strategy
than not trading. **The band rule is settled: demoted to a sensitivity, permanently, at this capital.**

That is not a defeat, it is the first thing either project line has actually settled with arithmetic.
It converts an open-ended strategy search into a bounded build, and it removes the temptation to
spend months on trade-policy optimisation that cannot earn 375 CNY.

---

## 6. Recommended direction

> **The new project is an account, not a signal.** Its job at 50,000-100,000 CNY is to hold a
> risk-capped ETF allocation through an append-only, cost-gated ledger that provably charges every
> fee the broker charges and cannot silently lose money to structure. Its contribution is a measured
> per-instrument-class feasibility map plus a net-CNY account contract, and its evidence is a forward
> paper book. Trade policy is settled by arithmetic and is not the subject.

What that means concretely:

1. **Default arm is static**: fixed target weights, cash as the fine stabiliser, rebalanced annually.
2. **Quarterly rebalancing is the comparator**, not the recommendation, because it costs 353 CNY/yr
   at 75k for a benefit nobody has demonstrated.
3. **The band rule exists only as a reported bound** and cannot set the shipped rule.
4. **The stabiliser is quantised honestly**: a bond sleeve is 0 %, 20-28 %, 40-56 % or nothing, and
   cash absorbs the remainder. The design must report the tracking error that quantisation costs,
   because that number is the real price of small capital.
5. **No forecasting, no ML, no factor search in v1.** Both prior projects are evidence that the
   machinery is not the bottleneck.

The honest caveat, stated so it cannot be discovered later: **nothing in this design generates alpha.**
Static allocation returns come from asset-class premia, which is a bet, not an edge. The project's
defensible value is that it stops the -94 % failure class and makes every CNY auditable. Whether a
return source is added on top is a separate decision, and it should be made deliberately rather than
smuggled in as "the strategy layer".

---

## 7. Architecture

Four layers, each with one job. The dependency direction is one-way until the loop closes at the
ledger.

```
instruments.parquet  bars.parquet  corp_actions.parquet      (frozen, hashed)
        |                  |                |
        +---------->  as-of session view  <+
                              |
                        ledger state  <-------------+
                              |                      |
                       target weights                |
                              |                      |
                    drift vs lot-rounded book        |
                              |                      |
             cost gate on POST-rounding notional     |
                              |                      |
              sells first -> buys from settled cash  |
                              |                      |
                    append fills / suppressions -----+--> daily.csv, decision.json
```

**Instrument metadata** (the table that makes the rest correct):

```
code name class settlement lot stamp_rate fee_profile listed_from listed_to
511010 bond     T+0  100  0.0         etf_std     2013-03-25   -
510300 equity   T+1  100  0.0         etf_std     2012-05-28   -
518880 commodity T+0 100  0.0         etf_std     2013-07-18   -
```
Settlement is per class and is *not* uniformly T+1 — equity ETFs are T+1, bond, gold and cross-border
ETFs commonly T+0. Stamp rate is 0 for every ETF; the 0.0005 rate belongs to stocks only.

**Six invariants.** These are the tests, not aspirations:

1. `NAV = cash + Σ(lots × close_raw)` and nothing else writes NAV.
2. Every fill's cost, recomputed independently from the fee schedule, equals the logged cost.
3. No order executes whose post-rounding notional is below `5 / (T - slippage - transfer)`.
4. A sell's proceeds are unavailable to buys until settlement, per instrument class.
5. Replaying the same window twice produces an identical ledger hash.
6. No sleeve is silently suppressed: it is either tradeable at the declared tolerance or flagged
   `FIXED` and held.

**Hand-computed tests** (the ones that catch real bugs): at a 16 CNY price, desired 4,800 / 5,000 /
5,100 all floor to 4,800 CNY and pay 5 CNY = 10.42 bp, so all three are suppressed at a 10 bp
tolerance and 6,400 is the first that clears; a 0-lot order pays 0; a sell of 150 shares trades 100;
a dividend on the ex-date raises cash without changing lots; a suspension produces a stale mark and
zero fills; a T+1 buy cannot be sold the same session.

---

## 8. Framework and build order

Stack: the existing `D:\minequant\.venv` (pandas 3.0.5, numpy 2.5.2, duckdb 1.5.5, pyarrow 24.0.0,
akshare 1.18.91). Parquet for panels, JSONL for the ledger, `duckdb` for ad-hoc queries. No GPU, no
cloud, no new dependencies. Total budget: 3-4 days.

| step | deliverable | why first |
|---|---|---|
| 1 | frozen panel + instrument/fee/settlement table, both hashed | every later number depends on it, and it is the artefact that cannot be chosen after seeing results |
| 2 | ledger + the six invariants as tests | this is the part that must be right forever |
| 3 | feasibility report from the frozen panel | stands alone as a deliverable even if nothing else is built |
| 4 | three-arm replay: static-annual, quarterly, band-sensitivity, decomposed into cost saved vs gross exposure difference | answers the trade-policy question in one run |
| 5 | forward paper book: append daily, never rewrite | the only evidence that counts from here on |

Step 3 alone justifies the build. Step 4 is what makes the ledger comparable to something.

---

## 9. Kill criteria

Written down before the first replay, so the result cannot be reinterpreted afterwards.

- If the static arm's structural drag exceeds 0.5 % of capital per year at 50k, the sleeve count is
  too high for the capital: reduce instruments rather than accept the drag.
- If the band arm cannot make most sleeves tradeable at 50k, trade policy is closed permanently at
  annual-only and is not revisited until capital changes by 5×.
- If realised risk exceeds the mandate in more than 10 % of sessions, the "cash carries the fine
  adjustment" assumption has failed, and the honest fallback is a coarse 20-28 % bond block with the
  tracking error reported, not hidden.
- If the static arm's return over the forward paper book is indistinguishable from buy-and-hold of a
  single broad ETF, the allocation layer has earned nothing and should be replaced by the simpler
  thing.

---

## 10. Open questions

1. **Where does the return come from?** Unanswered, and it is now the central question rather than a
   footnote. Static asset-class premia are a bet. If the answer is "a bet is fine", the project is
   infrastructure and should be scoped as infrastructure.
2. **Is a bond sleeve measured as a stabiliser, or only labelled as one?** The granularity census is
   by instrument class. Realised volatility and correlation against the equity sleeve is the
   measurement still owed, and it is what would make or break the "anti-correlated" claim.
3. **What is the measured one-way spread?** 5 bp is inherited from P1's fee matrix, not measured, and
   it dominates the ceiling: at 1 bp the ceiling halves, at 15 bp it triples and trade policy becomes
   worth testing again.
4. **Do bond ETF unit prices stay near par?** The 52-instrument census is a 2026-11 snapshot; new
   ETFs list at par, so the constraint is structural rather than incidental.

---

## 11. One change made to your machine

`D:\deepseek-harness\presets\personal-quant\kernel.js:4462` tested
`if (finding.support === undefined) finding.support = {...}` before incrementing
`finding.support[state]`. Round-1 findings persist `support: null`, so every `stage=cross` call threw
`Cannot read properties of null (reading 'agree')` and the review could not proceed. Patched to
`if (finding.support == null)`. `node --check kernel.js` passes and the cross round then ran. This is
your harness checkout, not the project, so it is flagged here rather than buried.