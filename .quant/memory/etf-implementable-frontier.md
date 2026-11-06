# Working memory — etf-implementable-frontier

- **Question**: Which allowed composition to build and hold at 50-100k, given the cost gate refuses most re-targets and no mean-return difference is measurable at this capital?
- **Success**: A prespecified simpler policy either reproduces the adopted book's terminal net CNY within a declared tolerance with no worse daily-marked drawdown/vol at every entry start (construction retired), or it does not (construction has a measured reason to exist on this path); the probe must first reproduce the recorded +1542.79 CNY/yr.
- **Next**: Run the retirement probe: add Arm kind 'hold', run the single-start hold-vs-lots reproduction at 2016-01-04 / 50,000 / 15.1 first, and expand to the 12-start grid only if that does not already retire the construction; report daily-marked and monthly-marked risk side by side.

Mechanical check: 4 facts, 1 hypotheses, 0 flagged.

## Verified facts
- The engine already writes a per-session NAV (2430 rows) into ReplayResult.daily and E2/E3 persist only the monthly frame, so every published risk number is monthly-marked; daily-marked drawdown is worse by 2.23 pp (lots -14.50% vs -12.27%) and 1.80 pp (static -20.97% vs -19.17%) at 50,000 / tol 15.1 / measured. — holds in: the 2016-01-04..2025-12-31 replay window, any arm; evidence: next-round-composition-benchmark (next-round-composition-benchmark)
- The adopted book's daily basis is cagr 6.01%, vol 9.09%, maxDD -14.50% (Sharpe 0.66); 510300 buy-and-hold 5.47% / 21.76% / -44.75% (0.25); 511220 buy-and-hold 4.91% / 3.27% / -7.81% (1.50). — holds in: same window, qfq close, dividends adjusted; evidence: next-round-composition-benchmark (next-round-composition-benchmark)
- Runtime measured: one four-arm E3 cell 22.8 s at 50,000 (19.7 s at 120,000), one arm 6.5-10.2 s, E2's 17-cell x 3-arm sweep 983.3 s, so 120 cells is about 46 minutes. — holds in: this machine, market build included per cell; evidence: next-round-composition-benchmark (next-round-composition-benchmark)
- A buy executes at slot i+2 but at slot i+1 when i+2 is the last session, so execution lag depends on replay length and slicing a full-window daily frame cannot reproduce a standalone shorter replay. — holds in: any decision issued in the final two sessions of a replay window; evidence: next-round-composition-benchmark (next-round-composition-benchmark)

## Hypotheses
- The +1542.8 CNY/yr lots-vs-static contrast is a bundle (sleeve returns plus the lot rule's access to them) rather than an additive sleeve contribution, because removing bond moves the static comparator from 62,163.64 to 55,303. — counter-evidence: the three-bucket reconciled attribution has not been run; cash and rounding terms are unquantified; evidence: next-round-composition-benchmark

## Unresolved disagreement
- gpt-6.1-sol held the pilot (its brief showed the four author answers as null) while gemini4high judged R1 resolved and R2/R3 non-blocking; the round was recorded invest/explore with all four objections accepted, so the dissent stays open

## Done
- direction/architecture/completion review
- two-route review of the next direction (direction + cross, all four objections accepted)
- idea v2 + design v2, every design field carrying a condition and a measure
