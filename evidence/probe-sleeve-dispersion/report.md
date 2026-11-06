# What does the member-ordering lottery cost, by sleeve?

50 000 CNY, base regime (15.1 bp gate, lot floor, measured costs), every distinct ordering of
each sleeve's listed members, 2016-01-04..2026-11-04. Dispersion = (max-min)/mean of terminal
NAV across orderings, per cent. Terminal NAVs read from the 94 replays' ledgers.

| sleeve | mean dispersion (%) | truncated to fewer members? | members track | qfq CAGR spread (pp/yr) |
|---|---|---|---|---|
| equity | 0.000 | no - all listed members held at 50 000 | CSI 300 / CSI 500 / CSI 1000 | 3.68 |
| bond | 0.124 | early only (511380 lists 2020-04-07, k=2 once NAV grows) | 10y local-government bond / convertible bond | 2.32 |
| commodity | 0.567 | yes - always k=1 at 50 000 | Au99.99 / Au99.99 (same underlying) | 0.08 |
| overseas | 12.643 | yes - always k=1 at 50 000 | Nasdaq-100 / S&P 500 / Hang Seng | 18.65 |

| sleeve | 2016-01-04 | 2017-04-05 | 2018-07-02 | 2020-01-02 | 2021-10-08 | 2023-10-09 |
|---|---|---|---|---|---|---|
| equity | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| bond | 0.00 | 0.00 | 0.00 | 0.00 | 0.74 | 0.00 |
| commodity | 0.19 | 0.93 | 0.20 | 0.72 | 1.18 | 0.18 |
| overseas | 14.09 | 21.64 | 12.58 | 13.72 | 8.48 | 5.36 |

The 2x2 is clean: dispersion is ~0 in the two cells where either condition fails -
equity holds all its members (11.44 pp/yr of member spread would be reachable, 0.000 % realised)
and commodity is truncated but its two members track the same Au99.99 (0.567 %). It is large only
where the sleeve is BOTH truncated and its members are different exposures: overseas 12.643 %
against an 18.65 pp/yr member spread. Bond sits between (0.124 %) because it is truncated only
before 2020-04-07, and it proves the capital is not the variable: the same 35 % sleeve costs
almost nothing once its second member lists.

**Verdict:** exposure-reading-supported
