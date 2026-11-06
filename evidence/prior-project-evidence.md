# Prior-project evidence bundle

Verbatim excerpts, re-readable, with source path and line. Compiled 2026-11-04 so that review
citations resolve inside this workspace. Nothing here is paraphrased; each quote was read from
the file named beside it. Where a measurement is mine rather than the file's, it says so.

Two projects are surveyed:

- **P1** `D:/minequant/AlphaGPT` — A-share daily formula search (RL/GP/TPE/random over a DSL),
  backtest, and a simulated account.
- **P2** `D:/进益资本杯` — 2026 进益资本 Cup factor challenge: 中证1000 minute bars + 5-level book,
  predicting 30-minute forward VWAP return; end-to-end PyTorch entry.

---

## 1. P1 states its own failure in its own artifacts

### 1.1 The adjudication says no admissible formula exists

`D:/minequant/AlphaGPT/data/p11_searcher_comparison/adjudication.json:7058`

```json
"headline": "negative_no_admissible_formula",
```

with `admissible_arms: []`. Twelve arms (4 searchers x 3 seeds); only `tpe` seed42 cleared all
four gates. The three RL arms scored 0.0352 / 0.0753 / 0.0393 total return with excess
**-0.085 / -0.0496 / -0.0814** against the equal-weight benchmark.

### 1.2 Five folds, 55 candidates, median excess negative

`D:/minequant/AlphaGPT/data/protocol_result.json` — 2021-2025, 5 folds, 55 candidates:

- 6 / 55 with positive excess
- median excess **-0.1294**, mean -0.2121
- best +0.0652
- 0 / 55 with both excess > 0 and Sharpe > 1

### 1.3 The search objective did not predict money

`D:/minequant/AlphaGPT/reports/project-assessment-20261018T040526Z.json`, 270 shortlist rows:

- median net return **-6.3 %**
- median net excess **-9.4 %**
- median fee **9.9 % of initial capital**
- median realised exposure 0.669
- Spearman(validation reward, net return) = **-0.043**
- Spearman(validation reward, net excess) = **+0.102**
- `fee_sensitive` 53 / 55

### 1.4 The simulated account

`D:/minequant/AlphaGPT/data/sim_portfolio_state.json`: 2,822 sessions 20150106-20260814,
28,179 trades, 100,000 -> **5,946.37 (-94.05 %)**. `data/sim_progress.json` phase `"error"`;
`AlphaGPT/STOP_SIGNAL` contains `STOP`.

### 1.5 The one canonical self-admission

`D:/minequant/AlphaGPT/README.md:5`

> 历史数据已经反复用于开发，历史成绩不能作为新的独立样本外证据。

---

## 2. P1's execution layer: the fee model that already exists

### 2.1 Lot rounding happens on the delta, never on the held book

`D:/minequant/AlphaGPT/ashare_execution.py:22-35`

```python
def trade_share_delta(target: float, current: float, *, lot_size: int = 100) -> float:
    """Signed executable share change; round the delta, never the held book.

    Full exits may contain odd shares. The small numerical tolerance only
    reconciles weights rounded onto the constructor's 12-decimal grid.
    """
    delta = float(target) - float(current)
    if abs(delta) <= 1e-7:
        return 0.0
    if target <= 0.0 and delta < 0.0:
        return -float(current)
    if lot_size <= 0:
        return delta
    quantity = math.floor(abs(delta) / lot_size + 1e-9) * lot_size
    return math.copysign(quantity, delta)
```

### 2.2 The fee semantics, stated by the class itself

`D:/minequant/AlphaGPT/ashare_execution.py:69-72`

> `"""Exact fee model shared by every execution path.`
>
> `Commission is floored independently for every non-zero order. Stamp tax`
> `applies to sells only; transfer fees and slippage apply to both sides.`

### 2.3 The floor is a per-order maximum, not a rate

`D:/minequant/AlphaGPT/ashare_execution.py:133-146`

```python
nonzero = amount > 0.0
commission = np.where(
    nonzero,
    np.maximum(self.commission_rate * amount, self.min_commission),
    0.0,
)
stamp = (
    np.where(nonzero, self.stamp_tax_rate * amount, 0.0)
    if side == "sell"
    else np.zeros_like(amount)
)
transfer = np.where(nonzero, self.transfer_fee_rate * amount, 0.0)
slippage = np.where(nonzero, self.slippage_rate * amount, 0.0)
```

**Consequence that drives this project's design.** Because commission is a *floor per order*, the
breakeven order notional is `min_commission / target_rate`. At a 5 CNY floor and a 10 bp tolerance
that is **5,000 CNY**. Any order smaller than that pays more than 10 bp the instant it is sent.
This is the whole reason a no-trade band must be derived from the schedule rather than picked.

### 2.4 The schedule in force

`D:/minequant/AlphaGPT/data/fee_matrix.json` -> `fee_params`

```json
{"commission_rate": 0.00025, "min_commission": 5.0, "stamp_tax_rate": 0.0005,
 "transfer_fee_rate": 1e-05, "slippage_rate": 0.0005}
```

The accompanying `capacity` grid covers capitals 100k / 200k / 500k only, at 1, 2, 4, 6, 12, 26
positions: at 100k it reports capacity 5 for 6 positions and 0 for 12 or 26 positions at 6
turnovers per year. **50,000 CNY never appears in the grid.**

---

## 3. P2 built real predictive content and lost money on it — its own numbers

Source: `D:/进益资本杯/runs/a-gate/20261027T050733Z/day-set-result.json`, key `summary_rows`.
Every column below is read straight from that file; bp = basis points per rebalance snapshot
(there are about 8 snapshots per trading day). `cost_mean_5bp` uses the project's own house stress
rate of 5 bp one-way; `net_return_mean_5bp = long_short_return_mean_0bp - cost_mean_5bp`;
`breakeven_single_side_rate` is the one-way rate at which net is exactly zero.

| object | rank IC | gross LS spread (bp) | turnover | cost @5bp (bp) | net @5bp (bp) | breakeven one-way (bp) |
|---|---|---|---|---|---|---|
| reference_nine_blend | 0.0707 | 5.30 | 1.102 | 11.02 | **-5.73** | **2.40** |
| candidate_mlp_3seed | 0.0674 | 5.08 | 1.134 | 11.34 | -6.27 | 2.23 |
| candidate_patch_3seed | 0.0687 | 5.22 | 1.123 | 11.23 | -6.02 | 2.32 |
| candidate_tlob_3seed | 0.0702 | 5.27 | 1.130 | 11.30 | -6.05 | 2.32 |
| baseline_ridge_default | **0.0070** | 0.19 | **0.003** | 0.03 | **+0.17** | **29.94** |
| control_shuffled_reference | 0.0030 | 0.30 | 1.603 | 16.03 | -15.73 | 0.09 |
| control_sign_flipped_reference | -0.0707 | -5.30 | 1.103 | 11.03 | -16.32 | -2.40 |

Read the two bold rows together. **The arm with rank IC 0.0070 is the only one that is net-positive;
the arms with rank IC ~0.070 are all net-negative at the same cost.** A 10x difference in the
selection metric in the wrong direction. The sign-flipped control reproduces the reference
breakeven exactly (-2.40 vs +2.40), which confirms the arithmetic is internally consistent and the
result is not a coding artifact.

The mechanism is one line of algebra and it is not a modelling subtlety:

```
net = gross_spread - 2 * c * turnover        (cost = c * U, U = 2 * turnover)
breakeven c* = gross_spread / (2 * turnover) = 5.30 / (2 * 1.102) = 2.40 bp
```

So at a realistic stock one-way cost of ~7.5 bp (2.5 bp commission + 5 bp slippage, before the 5 bp
sell-side stamp), this family of strategies needs `turnover <= 5.30 / (2 * 7.5) = 0.353` per
snapshot to break even. It runs at 1.10 — **a factor of about 3 too fast**. No amount of model
improvement fixes a factor-of-3 turnover excess; the horizon has to change.

### 3.1 The cost layer existed and was never used as a gate

- `D:/进益资本杯/src/jinyiquant/evaluation.py:15` — "`cost = single_side_rate * U`. `turnover = U / 2`"
- `D:/进益资本杯/src/jinyiquant/evaluation.py:103-104` — "decimal one-side rate c applied to traded
  notional; **configured explicitly, otherwise cost/net are undefined and counted**"
- `D:/进益资本杯/src/jinyiquant/evaluation.py:301` — `def breakeven_single_side_rate(...)`
- `D:/进益资本杯/src/jinyiquant/config.py:206` — `single_side_rate: float | None = Field(default=None, ge=0, lt=1)`
- `D:/进益资本杯/src/jinyiquant/evaluation.py:356-357` — `elif single_side_rate is None: status = "undefined_single_side_rate_not_configured"`

Of 293 registered configs, the ones that set a rate mostly set `0.0`; 430 run artifacts carry
`undefined_single_side_rate_not_configured`. The team did define a `net5` calibre at
`single_side_rate = 5e-4` as a stress read, but the primary gate was rank IC. **The tool to price
the decision existed; the discipline to gate on it did not.** That is the transferable lesson, and
it is a sharper one than "they forgot costs".

---

## 4. The instrument-class measurements (mine, 2026-11-04)

No ETF panel exists in either project: `grep -i etf` over P1's `ashare_data`, `ashare_model` and
`config` returns 3 incidental hits, over `P2/src` returns 1, and P1's `ashare_v2.duckdb` has a
`stocks` table of 5,542 stock rows and no ETF table, while `daily_bar` holds 5,820 `ts_code` over
20140102-20261015. ETF history is therefore untouched by both.

**Step 1, a sample of ten.** Measured with `ak.fund_etf_hist_em(..., adjust='')`, last close around
2026-10, 198 daily rows each. `lot100` = one board lot; `% of 50k` = that lot as a share of a
50,000 CNY account.

| code | kind | last | lot100 (CNY) | % of 50k |
|---|---|---|---|---|
| 512880 | equity sector | 0.962 | 96.2 | 0.2 % |
| 588000 | STAR50 | 1.228 | 122.8 | 0.2 % |
| 513100 | Nasdaq cross-border | 2.239 | 223.9 | 0.4 % |
| 159915 | ChiNext | 2.435 | 243.5 | 0.5 % |
| 510300 | CSI300 | 4.065 | 406.5 | 0.8 % |
| 510500 | CSI500 | 6.305 | 630.5 | 1.3 % |
| 518880 | gold | 8.115 | 811.5 | 1.6 % |
| 511360 | short-duration bond | 114.124 | 11,412.4 | **22.8 %** |
| 511260 | 10y treasury | 135.327 | 13,532.7 | **27.1 %** |
| 511010 | treasury | 141.123 | 14,112.3 | **28.2 %** |

**Step 2, the whole universe.** Ten instruments cannot support a claim about an asset class, so the
population was measured. Two boards had to be read because the Shanghai/Shenzhen spot board omits
bond ETFs entirely (`ak.fund_etf_spot_em()` returns 1,664 rows and zero names containing 债; 511010,
511260, 511360, 511380 and 511220 are all absent from it). Bond instruments were therefore taken
from the Sina ETF list (`ak.fund_etf_category_sina(symbol='ETF基金')`, 1,717 rows, 52 names
containing 债 with a live price). Raw pulls are `etf_spot_raw.csv`, `etf_universe_classified.csv`
and `bond_etf_measured.csv` beside this file.

| sleeve | n | unit price (median) | lot100 (median) | lot as % of 50k (median) | range | n at ≤5 % |
|---|---|---|---|---|---|---|
| commodity | 45 | 0.90 | 89 | 0.2 % | 0.1-1.7 % | 45 / 45 |
| equity | 1,351 | 0.99 | 99 | 0.2 % | 0.1-20.0 % | 1,350 / 1,351 |
| overseas | 242 | 0.93 | 92 | 0.2 % | 0.1-0.6 % | 242 / 242 |
| cash-like (money-market) | 26 | 100.00 | 9,999 | **20.0 %** | 20.0-20.2 % | **0 / 26** |
| bond | 52 | 102.84 | 10,284 | **20.6 %** | 2.1-28.3 % | **3 / 52** |

The return-seeking sleeves are effectively continuous at this capital: 1,637 of 1,638 instruments
cost under 5 % of a 50k account per lot, median 0.2 %. The one equity outlier is 159005 快钱ETF汇添富
at 100.000, a cash-management product, not equity.

The stabilising sleeves are not. All 26 money-market ETFs quote at par ≈100 CNY, so one lot is
20.0 % of 50k, 13.3 % of 75k and 10.0 % of 100k. Of the 52 bond ETFs, only three fall under 5 %, and
**all three are anti-stabilisers**:

| code | name | price | % of 50k | why it does not stabilise |
|---|---|---|---|---|
| 511220 | 城投债ETF海富通 | 10.441 | 2.1 % | LGFV credit risk, not a rate hedge |
| 511180 | 可转债ETF海富通 | 11.621 | 2.3 % | convertible = equity beta in disguise |
| 511380 | 可转债ETF博时 | 12.539 | 2.5 % | same |

The instruments that genuinely damp a portfolio are all par-quoted and coarse: 511360 at 22.8 %,
511260 at 27.1 %, 511010 at 28.2 %, with 511520 政金债, 511200 信用债 and 511110 公司债 all in the
100-141 CNY band. **Within fixed income, granularity and stability are anti-correlated at this
capital.** The only finely divisible stabiliser is uninvested cash, which carries no lot constraint
at all.

The consequence is a discrete feasibility set, not a continuous one. At 50k the stabilising sleeve
can only take values near 0 %, 20-28 % (one bond lot), 40-56 % (two lots) and so on, with cash
absorbing every intermediate value. A weight vector optimised in continuous space is therefore not
directly implementable: the optimiser's stabiliser weight has to be quantised, and the residual
rebound onto cash. That quantisation step, and its cost in tracking error against the continuous
target, is a real part of the problem rather than a rounding detail.

---

## 5. What this bundle does and does not establish

**Establishes.** P1 has no admissible net formula and its selection objective was uncorrelated with
money. P2 has measurable gross predictive content whose breakeven cost (2.2-2.4 bp one-way) sits
below any realistic cost, and whose only net-positive member is the arm that barely trades. The
account-level constraint at small capital is the per-order fee floor interacting with lot
granularity, and fixed-income ETFs are the binding sleeve.

**Does not establish.** Any claim that an ETF allocation earns a positive net return. Any claim that
the ETF panel is an out-of-sample holdout — it is unread history, which is weaker than future
observation. Any claim that a band rebalancing rule beats scheduled rebalancing; that is the
question, and it is unanswered until measured.