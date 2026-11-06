# E2 — three-arm replay to net CNY

Window 2016-01-04 .. 2025-12-31 (2430 sessions, 120 month-end decisions). Run `e2-trade-policy-replay`, 17 cost cells, 983 s wall. Code `newquant/eval/e2.py` over `newquant/replay.py`.

One cost model throughout — 2.5 bp commission floored at 5 CNY per non-zero order, ETF stamp duty 0, 0.01 bp transfer, slippage = the measured half tick frozen per instrument — and one execution path: decide at the month-end close, sell at the next open, buy at the open after the sale settles, every intent through the same post-rounding cost gate inside one append-only hash-chained ledger.

## 1. The constraint that binds before any drift exists

At 75,000 NAV and a 15.1 bp gate the smallest order the gate accepts is 3,345 CNY, the median across the ten tradable codes and both sides is 3,669 CNY, the largest is 5,066 CNY. A sleeve of weight w spread equally over k codes is tradable only if w x NAV / k clears that floor:

| sleeve | weight | members | slice at this NAV | member floor (worst) | executable |
|---|---|---|---|---|---|
| equity | 45 % | 3 | 11,250 | 5,066 | yes |
| bond | 35 % | 2 | 13,125 | 3,435 | yes |
| commodity | 10 % | 2 | 3,750 | 3,669 | yes |
| overseas | 10 % | 3 | 2,500 | 4,436 | **no** |

The overseas sleeve cannot be entered at all at this size: its per-code slice is below the floor, so every one of its entry orders is refused before it reaches the book and the account holds the difference as cash. That is F-113a8e8d-6 answered from the other end than the question asked it — the minimum order does not merely freeze marginal rebalancing, it makes a whole sleeve unreachable.

| arm | codes never filled | cash weight at entry | cash at end | equity target / realised at end |
|---|---|---|---|---|
| static | 159920, 513100, 513500 | 33.2 % | 10.5 % | 0.450 / 0.381 |
| vol | 159920 | 33.2 % | 0.4 % | 0.483 / 0.466 |
| rule | 159920, 513100, 513500 | 33.2 % | 16.7 % | 0.450 / 0.417 |

The static arm never owns 159920, 513100, 513500: 33 intents over ten years, zero fills. What the replay calls `static-annual` is therefore the 45/35/10/10 mandate holding 33.2 % of the account in cash at entry and 10.5 % at the end — the arm is not a policy, it is the mandate plus an execution failure, and every Δ below is measured against that.

## 2. Primary cell — 75,000 NAV, 15.1 bp, measured slippage

| arm | end NAV | CAGR | vol | max DD | cost bp/yr | turnover/yr | fills / intents | gate-suppressed | granularity TE | gate TE |
|---|---|---|---|---|---|---|---|---|---|---|
| static | 105,810 | 3.50 % | 9.4 % | -16.3 % | 0.84 | 0.130 | 10 / 102 | 82 | 7.1 % | 24.5 % |
| vol | 111,304 | 4.03 % | 9.9 % | -22.2 % | 6.93 | 0.726 | 86 / 1038 | 773 | 6.6 % | 27.3 % |
| rule | 109,243 | 3.83 % | 9.7 % | -15.9 % | 1.06 | 0.145 | 13 / 1038 | 772 | 7.2 % | 22.7 % |

Granularity TE is the distance from the aimed weights to what board lots allow; gate TE is the distance from that to what was actually held, i.e. the drift the gate let through by refusing orders. For the static arm the second is 3.4x the first, so on these data the cost gate, not the 100-share lot, is the dominant source of tracking error.

Δ net CNY against the static arm in the same cell:

| candidate | annual CNY | 90 % CI | cumulative | sd/month | MDE |
|---|---|---|---|---|---|
| vol vs static | 417 | [-716, 1,666] | 4,173 | 571 | 1,750 |
| rule vs static | 259 | [-4, 580] | 2,593 | 178 | 545 |

The vol arm's advantage is two episodes rather than a tendency: 2016 0, 2017 -132, 2018 4,385, 2019 -736, 2020 209, 2021 -848, 2022 -1,109, 2023 -2,535, 2024 4,515, 2025 424. It is positive in 4 of 10 years and its own drawdown is worse (-22.2 % against -16.3 %), which is the opposite of what a volatility conditioner exists to do.

## 3. Tolerance sweep at 75,000 (measured slippage)

The same three arms under five gates. `static end` is the control that matters: it is what the baseline is worth as the gate is loosened, before any arm choice.

| tolerance bp | static fills | static cost bp/yr | static end NAV | Δ vol | Δ rule | Δ vol 90 % CI | Δ rule 90 % CI |
|---|---|---|---|---|---|---|---|
| 10.0 | 7 | 0.62 | 94,979 | 915 | -26 | [-343, 1,922] | [-211, 154] |
| 15.1 | 10 | 0.84 | 105,810 | 417 | 259 | [-716, 1,666] | [-4, 580] |
| 30.0 | 32 | 2.48 | 133,645 | -177 | -201 | [-1,155, 954] | [-455, 131] |
| 50.0 | 39 | 2.96 | 131,307 | -451 | -357 | [-1,302, 536] | [-534, -88] |
| 75.0 | 43 | 3.24 | 131,933 | -624 | -241 | [-1,509, 301] | [-501, 116] |

Across the sweep the static arm alone moves from 94,979 to 133,645 — a 41 % swing in terminal wealth produced by one policy number nobody would call a strategy parameter. Every Δ between arms in the same row is an order of magnitude smaller than that swing, and the arm difference flips sign 1 time(s) inside it: the conditioned arms win only where the baseline is crippled and lose wherever the baseline can trade. The trade mechanism dominates the state conditioning, and it dominates it in a way that is not monotone in the gate either.

Sign agreement across the sweep (measured slippage, 75,000): vol 2/5 positive, stable=False; rule 1/5 positive, stable=False. By the pre-registered rule a sign change voids adoption rather than being averaged away.

## 4. NAV sensitivity (measured slippage)

| NAV | tolerance bp | Δ vol | Δ rule | static fills | clearing min | intents below clearing |
|---|---|---|---|---|---|---|
| 50,000 | 15.1 | 58 | -18 | 6 | 3,345 | 94.12 % |
| 50,000 | 50.0 | -155 | -41 | 34 | 1,004 | 63.73 % |
| 75,000 | 15.1 | 417 | 259 | 10 | 3,345 | 90.20 % |
| 75,000 | 50.0 | -451 | -357 | 39 | 1,004 | 57.84 % |
| 100,000 | 15.1 | 429 | -5 | 20 | 3,345 | 79.41 % |
| 100,000 | 50.0 | -461 | -307 | 42 | 1,004 | 53.92 % |

Scaling the capital does not rescue the arms: the smallest Δ appears at the smallest account, and the interval widens with capital because the arms' return paths diverge less while the monthly dispersion of their difference grows.

## 5. Cost-model sensitivity at the primary cell

| slippage model | arm | end NAV | cost bp/yr | fills | Δ vs static (same model) |
|---|---|---|---|---|---|
| measured | static | 105,810 | 0.84 | 10 | — |
| measured | vol | 111,304 | 6.93 | 86 | 417 |
| measured | rule | 109,243 | 1.06 | 13 | 259 |
| flat | static | 94,944 | 1.10 | 7 | — |
| flat | vol | 106,942 | 6.99 | 58 | 930 |
| flat | rule | 93,913 | 1.06 | 7 | -63 |
| worst | static | 107,335 | 0.96 | 10 | — |
| worst | vol | 107,457 | 5.34 | 67 | 88 |
| worst | rule | 105,560 | 1.03 | 11 | -115 |

`measured` is the half tick per instrument, `flat` the inherited 5 bp constant, `worst` the half tick at each instrument's minimum price. The ranking is not stable across them — a further reason the primary number is a bound, not an estimand.

## 6. Distribution and unit-change accounting (F-60b5f78a-7)

| arm | dividends credited | total gain | dividends as share of gain | split residual cash |
|---|---|---|---|---|
| static | 9,390 | 30,810 | 30.48 % | 211 |
| vol | 9,842 | 36,304 | 27.11 % | 225 |
| rule | 9,506 | 34,243 | 27.76 % | 211 |

Without the distributions the static arm's ten-year total return would be 28.56 % instead of 41.08 % — about 1.25 percentage points of annual return withdrawn from a comparison whose entire margin is 0.5 pp (an upper bound: it does not compound the distributions). The treatment is not a detail; it is the same order of magnitude as the effect being tested.

Dividends are credited as cash on the ex-date from the fund's own distribution record, never from a price ratio: eastmoney 前复权 turned out to be a nonlinear rescale of the raw series for nine of fifteen codes, so inverting it books drift as distributions (`data/build_corp_actions.py`, check `qfq_usable_as_scale`). Five unit changes are applied as lot ratios with the truncated fraction paid as cash, so NAV is continuous across a split (511220 10:1 on 2023-01-16, 513100 5:1, 513500 2:1, 512100 0.365708, 510500 0.279944 pre-window).

## 7. Decision rule, clause by clause

Pre-registered threshold 375 CNY/yr = 0.5 % of capital at 75 000. Baseline frozen by the gate: **True**.

| candidate | CI excludes zero | point >= threshold | MDE > threshold | adopt |
|---|---|---|---|---|
| vol vs static | False | True | True | False |
| rule vs static | False | False | True | False |

**Reading.** unmeasurable at this capital: the minimum detectable effect is 1,750 CNY/yr against a 375 threshold, so no difference below 2.3 % of capital could have been certified on this window; the baseline it would have been certified against is itself frozen by the gate, and the reading band-rule-demoted-scoped applies.

Three independent grounds, all fixed before the run, point the same way: the interval covers zero, the design's minimum detectable effect is 4.7x the threshold that would have to be cleared, and the sign of the difference reverses where the baseline is allowed to trade. No arm is adopted and the tolerance is not retuned.

## 8. What this does not establish

1. One venue, one mandate, ten years, 120 monthly decisions. The interval covers estimation noise on this window, not regime change on the next one.
2. The arms differ only in their equity weight; bond, commodity and overseas weights scale with `(1 - w_eq)/(1 - 0.45)` in all three, so nothing here says the non-equity sleeves are correctly sized — and section 1 shows one of them was never bought.
3. Slippage is the measured half tick, i.e. a floor, not an impact model. Realised cost on orders above 20 k CNY would be higher and is unmeasured; the `worst` row bounds that direction, it does not estimate it.
4. `rule` carries four fitted coefficients refit annually on an expanding window, but the fits are near zero for the first three refits, so for 2016-2019 it is the mandate on a monthly calendar and its Δ is exactly zero by construction. Its effective sample is six years, not ten.
5. Positions are marked at the last close and NAV has a single writer; a stale mark on a suspended code would move NAV without a trade, which the venue's gap-day flags make unlikely but do not exclude.
