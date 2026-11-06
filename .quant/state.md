> **STALE VIEW — frozen at ledger seq 42.** The authority is the handoff at
> `.quant/handoff/etf-implementable-frontier.md` (seq 95, hash d417e9cc6667),
> rebuilt from `node <kernel> state` when the preset is mounted. Through seq 95 the
> build added E3 (step 6.5) and design v14; nothing below seq 42 reflects that.

# Current research state

Rebuilt from the ledger at head seq 42. Regenerate with `quant_ledger op=state`; never hand-edit.

## Facts (adopted)
- At 50,000-100,000 CNY a trade-policy band cannot pay for itself. Commission-floor avoidance is capped at 240 CNY a year for 12 instruments at quarterly cadence (0.32 percent of 75,000). The whole annual trading budget, extending from the floor to total cost, is 40 orders at 8.82 CNY = 353 CNY (0.47 percent), which bounds any possible band saving and sits below the 375 CNY hurdle, so the experiment could not have succeeded on its own terms. Separately, at 50,000 CNY with ten sleeves of 5,000 CNY a 15.1 bp tolerance demands a 5,000 CNY order, the entire sleeve, so no partial drift can clear the gate and the band rule degenerates into a hold. The band rule is demoted to a sensitivity; the project's core is the append-only net-CNY ledger plus the measured per-instrument-class feasibility map, whose value is avoiding the prior projects' loss class rather than producing edge, and the return source is now the open question.
  applies when: Holds for a China A-share ETF account of 50,000-100,000 CNY with 8-12 sleeves, board lots of 100 shares, commission floored at 5 CNY per non-zero order, ETF stamp duty zero, transfer 1e-05, and one-way slippage around 5 bp. It does not hold for accounts large enough that the fixed 5 CNY becomes a few basis points of a slice, nor for instruments whose measured spreads are far below 5 bp.
  (band-rule-demoted-scoped, seq 34; evidence: D:/newquant/evidence/prior-project-evidence.md, round-737a812e-0c76-41cd-be60-d8e660b5f78a)
- The neural network belongs at the stock-panel layer, not at the monthly allocation layer. A model fitted on about 900 basket-months is capped near 18 parameters by a 50-observations-per-parameter budget, which admits a rule or a tight linear model and rejects a network by construction; a model fitted on the stock panel draws its sample from millions of rows and can carry nonlinearity, after which aggregation and allocation must stay tiny. Both reviewers reached this independently, and it converts the user's neural-network ambition from a statistical impossibility into a well-posed two-layer design.
  applies when: Holds while the traded book is 6-8 ETF sleeves at 50,000-100,000 CNY and the estimation data is P1's A-share daily panel (12,008,787 rows, 5,820 codes, 20140102-20261015). The parameter-budget arithmetic (900 basket-months / 50 = 18 parameters) applies to any model fitted directly on basket-month rows; it does not bind a model fitted on the stock panel and aggregated afterwards.
  (nn-belongs-at-panel-layer, seq 41; evidence: round-8d9f917d-b155-4e92-8514-98b5113a8e8d, D:/newquant/evidence/prior-project-evidence.md, D:/minequant/AlphaGPT/data/ashare_v2.duckdb)

## Decisions (adopted)
- Adopt all six cross-round corrections. (1) The fee-floor/band test applies to the FINAL post-rounding executable notional and to TOTAL one-way cost (commission + slippage 5bp + transfer 0.1bp), never to the pre-rounding desired notional and never to commission alone; a failing order is suppressed rather than resized. (2) Drop the derived "3x horizon change" claim: at 5bp breakeven turnover is 0.53 (a 2.08x reduction) and a horizon change also moves gross spread, so the only defensible statement is that cost-adjusted implementability must enter selection. (3) Never claim either prior project lacked execution-cost accounting; P2 had single_side_rate and breakeven_single_side_rate, P1 had ExecutionCostModel and fee_matrix.json; the defect is that neither gated on cost, so the new claim is a stricter account-level selection contract. (4) Run 75,000 CNY directly alongside 50,000 and 100,000 because lot and fee discontinuities make the interior point non-deducible. (5) Freeze exactly ONE band rule before the first replay and report any grid as sensitivity analysis only; a preregistered grid does not make its winner independent evidence. (6) Restrict feasibility claims to the measured universe: 1,637/1,638 return-seeking instruments cost <=5% of 50k per lot, while 26/26 money-market ETFs cost 20.0% and 49/52 bond ETFs cost 20.6% median, the three cheap bond ETFs all being credit or convertible rather than stabilisers.
  applies when: Holds for a China A-share ETF account of 50,000-100,000 CNY trading board lots of 100 shares at broker rates commission 0.00025 floored at 5 CNY per non-zero order, stamp duty 0.0005 on sells, transfer 1e-05, slippage 0.0005. The universe figures are a 2026-11 spot snapshot and will drift as new ETFs list at par.
  (cross-fixes-v4, seq 24; evidence: D:/newquant/evidence/prior-project-evidence.md, D:/newquant/evidence/etf_universe_classified.csv, D:/newquant/evidence/bond_etf_measured.csv, D:/newquant/evidence/etf_spot_raw.csv, round-46d6561c-96b1-4869-93c6-e78b6bf56322)

## Hypotheses (unverified)
None recorded.

## Retired conclusions
- At 50,000-100,000 CNY a trade-policy band cannot pay for itself, so the band rule is demoted and the project's core is the account ledger plus the measured feasibility map
  reason: superseded by a later conclusion (by band-rule-demoted-scoped)
  (band-rule-demoted-by-ceiling, seq 32)

## Re-check before relying (dependency moved)
None.

## Open objections (unanswered)
- [high] [method] The fee calculation establishes a minimum admissible order; it does not establish that the resulting band compensates for exposure drift. The proposed experiment must demonstrate that additional economic claim.
  cited: record:m00279 (not-found)
  (F-60b5f78a-1, open, round round-737a812e-0c76-41cd-be60-d8e660b5f78a)
- [high] [method] Under the stated maximum of twelve instruments and quarterly net rebalancing, eliminating commission-floor surcharges alone cannot clear the 375 CNY annual hurdle: its ceiling is 240 CNY, excluding common entry and exit. A passing result needs cost and exposure attribution.
  cited: record:m00279 (not-found)
  (F-60b5f78a-2, open, round round-737a812e-0c76-41cd-be60-d8e660b5f78a)
- [high] [evidence] The population measurement establishes granularity by instrument classification. It does not measure the claimed relationship between granularity and portfolio stability. That claim requires risk evidence for the actual holdings and target portfolio.
  cited: record:m00279 (not-found)
  (F-60b5f78a-3, open, round round-737a812e-0c76-41cd-be60-d8e660b5f78a)
- [high] [method] The cost gate requires a minimum post-rounding executed notional of ~5,000 CNY to cap the 5 CNY commission floor at 10.0bp (15.1bp total one-way), which means in a 50,000 CNY account across 8-12 ETFs (average sleeve 4,166-6,250 CNY), every partial drift rebalance trade is smaller than 5,000 CNY and will be permanently suppressed by the post-rounding gate, turning the band rule into a no-trade freeze except on full sleeve liquidations.
  cited: D:/newquant/evidence/prior-project-evidence.md:10 (quote-missing)
  (F-60b5f78a-5, open, round round-737a812e-0c76-41cd-be60-d8e660b5f78a)
- [high] [method] The 900 basket-month count overstates the information available for a common monthly timing target. This objection would be resolved by demonstrating additional sleeve-specific information and estimating uncertainty with dependence across sleeves and dates preserved.
  cited: unanchored — supplied “THE SAMPLE PROBLEM, STATED BEFORE THE REVIEW” excerpt. (not-found)
  (F-113a8e8d-1, open, round round-8d9f917d-b155-4e92-8514-98b5113a8e8d)
- [high] [task] Separating estimation breadth from holding breadth does not establish a new predictive contribution. The missing demonstration is that the panel-trained nonlinear model improves executable monthly outcomes beyond a linear model using the same factors and aggregation.
  cited: unanchored — supplied version-3 “difference from what the project already tried.” (not-found)
  (F-113a8e8d-2, open, round round-8d9f917d-b155-4e92-8514-98b5113a8e8d)
- [high] [method] Failure of one timing rule is insufficient evidence to reject every learned predictor. It is a valid complexity benchmark; a statistical veto would require evidence that the candidate information lacks useful monthly signal.
  cited: unanchored — supplied rough design, “simplest,” holds-when clause. (not-found)
  (F-113a8e8d-3, open, round round-8d9f917d-b155-4e92-8514-98b5113a8e8d)
- [high] [task] A realised-drawdown check cannot enforce a prospective 27% ceiling under monthly trading and gaps. This objection would be resolved by defining the ceiling as an evaluation rejection rule or supplying a proven construction that bounds future losses.
  cited: unanchored — supplied rough design, “goal,” how-you-would-know clause. (not-found)
  (F-113a8e8d-4, open, round round-8d9f917d-b155-4e92-8514-98b5113a8e8d)
- [high] [method] If the learned model is fitted on aggregated features at the basket-month level (~900 observations), the hard gate of 50 observations per parameter caps the model at ~18 parameters, which deterministically triggers the failure-handling fallback for any neural network; for a neural network to ever execute without violating the gate, estimation must occur on the stock-level cross-sectional panel before basket aggregation, which contradicts the `scale` assumption that model training is trivial single-process CPU compute on 900 rows.
  cited: D:/newquant/docs/new-project-direction-and-plan.md:1 (quote-missing)
  (F-113a8e8d-5, open, round round-8d9f917d-b155-4e92-8514-98b5113a8e8d)
- [medium] [method] The fee specification is internally inconsistent: the goal applies sell-side stamp duty while the ETF experiment specifies exemption. Resolve the applicable instrument-level charges before hashing the rule, because they change admissibility and reported net returns.
  cited: record:m00279 (not-found)
  (F-60b5f78a-4, open, round round-737a812e-0c76-41cd-be60-d8e660b5f78a)
- [medium] [task] The system specification contradicts itself on ETF stamp duty: the goal specifies "stamp duty 0.0005 on sells" while the cheapest check specifies "ETF stamp rate 0" and the boundary math (10.0bp commission + 5bp slippage + 0.1bp transfer = 15.1bp) assumes zero stamp duty.
  cited: D:/newquant/evidence/prior-project-evidence.md:10 (quote-missing)
  (F-60b5f78a-6, open, round round-737a812e-0c76-41cd-be60-d8e660b5f78a)
- [medium] [method] Sizing lots on RAW prices while deriving NAV solely from positions and cash in the append-only ledger without an explicit dividend/split event feed will miscalculate net CNY return whenever bond or equity ETFs pay cash dividends or split.
  cited: D:/newquant/evidence/prior-project-evidence.md:10 (quote-missing)
  (F-60b5f78a-7, open, round round-737a812e-0c76-41cd-be60-d8e660b5f78a)
- [medium] [problem] At 50,000 CNY across 6 sleeves (~8,333 CNY average sleeve size), a 5 CNY minimum commission requires a minimum order of 2,500 CNY (30% sleeve turnover) just to hit a 20bp one-way fee, and 3,000+ CNY once 100-share board-lot rounding and 5bp slippage are included; this will force most marginal monthly weight adjustments into the `FIXED` state, potentially making the learned model's monthly continuous risk-score indistinguishable from the coarse 2-3 parameter rule in realized ledger fills.
  cited: D:/newquant/evidence/prior-project-evidence.md:1 (quote-missing)
  (F-113a8e8d-6, open, round round-8d9f917d-b155-4e92-8514-98b5113a8e8d)
- [low] [evidence] The 52-instrument bond ETF granularity census is a single 2026-11 spot snapshot and the historical ETF panel has no forward out-of-sample fills until the paper book begins.
  cited: D:/newquant/evidence/prior-project-evidence.md:24 (quote-missing)
  (F-60b5f78a-8, open, round round-737a812e-0c76-41cd-be60-d8e660b5f78a)

  