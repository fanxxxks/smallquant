# Feasibility at 50,000, 75,000, 100,000 CNY

venue hash `d6a6e438e32e818f7d6382f413ea2739e016513147974d718632db204f8177ec` · bars to 2026-11-04 · 131 months · fee profile `etf_std`

Model-free: price × lot size × fee schedule only. A monthly trade of `f × NAV` is
floored to whole lots and then put through the same gate the account uses.

## A. Smallest trade that clears a tolerance

| tol (bp) | min order (CNY) | 50 k | 75 k | 100 k | inside the 12.5 %/sleeve budget |
|---|---|---|---|---|---|
| 7.6 | 20000.00 | 40.00% | 26.67% | 20.00% | **no** |
| 10 | 10204.09 | 20.41% | 13.61% | 10.20% | **no** |
| 15.1 | 5000.00 | 10.00% | 6.67% | 5.00% | yes |
| 30 | 2008.04 | 4.02% | 2.68% | 2.01% | yes |
| 50 | 1114.00 | 2.23% | 1.49% | 1.11% | yes |
| 75 | 716.00 | 1.43% | 0.95% | 0.72% | yes |

Annual turnover ≤ 6 → monthly total ≤ 50.0% of NAV
→ 12.50% per sleeve across four investable sleeves.

## B. Cleared share of (month × instrument) cells

| tol (bp) | trade/sleeve | 50 k | 75 k | 100 k |
|---|---|---|---|---|
| 10 | 2.5% | 0.0% | 0.0% | 0.0% |
| 10 | 5.0% | 0.0% | 0.0% | 0.0% |
| 10 | 10.0% | 0.0% | 0.0% | 0.0% |
| 10 | 12.5% | 0.0% | 0.0% | 93.9% |
| 10 | 20.0% | 0.0% | 93.9% | 99.7% |
| 15.1 | 2.5% | 0.0% | 0.0% | 0.0% |
| 15.1 | 5.0% | 0.0% | 0.0% | 0.1% |
| 15.1 | 10.0% | 0.1% | 93.9% | 99.7% |
| 15.1 | 12.5% | 93.9% | 95.1% | 100.0% |
| 15.1 | 20.0% | 99.7% | 100.0% | 100.0% |
| 30 | 2.5% | 0.0% | 0.0% | 87.8% |
| 30 | 5.0% | 87.8% | 93.9% | 93.9% |
| 30 | 10.0% | 93.9% | 93.9% | 99.7% |
| 30 | 12.5% | 93.9% | 95.1% | 100.0% |
| 30 | 20.0% | 99.7% | 100.0% | 100.0% |

## C. One-lot drag (smallest possible position)

| code | sleeve | one lot (CNY) | 50 k | 75 k | 100 k |
|---|---|---|---|---|---|
| 159915 | equity | 256 | 0.51% | 0.34% | 0.26% |
| 159920 | overseas | 140 | 0.28% | 0.19% | 0.14% |
| 159934 | commodity | 860 | 1.72% | 1.15% | 0.86% |
| 510300 | equity | 418 | 0.83% | 0.56% | 0.42% |
| 510500 | equity | 666 | 1.33% | 0.89% | 0.67% |
| 511010 ⚠ | bond | 14,135 | 28.27% | 18.85% | 14.14% |
| 511220 | bond | 1,044 | 2.09% | 1.39% | 1.04% |
| 511260 ⚠ | bond | 13,578 | 27.16% | 18.10% | 13.58% |
| 511380 | bond | 1,254 | 2.51% | 1.67% | 1.25% |
| 511880 ⚠ | cash | 10,093 | 20.19% | 13.46% | 10.09% |
| 511990 ⚠ | cash | 9,999 | 20.00% | 13.33% | 10.00% |
| 512100 | equity | 265 | 0.53% | 0.35% | 0.27% |
| 513100 | overseas | 224 | 0.45% | 0.30% | 0.22% |
| 513500 | overseas | 261 | 0.52% | 0.35% | 0.26% |
| 518880 | commodity | 823 | 1.65% | 1.10% | 0.82% |

## E. Action granularity (smallest executable move, and the annual pool)

| tol (bp) | NAV | min action (CNY) | % NAV | lumps the annual cap allows |
|---|---|---|---|---|
| 10 | 50,000 | 10,205 | 20.4% | 26 |
| 10 | 75,000 | 10,205 | 13.6% | 39 |
| 10 | 100,000 | 10,205 | 10.2% | 53 |
| 15.1 | 50,000 | 5,010 | 10.0% | 52 |
| 15.1 | 75,000 | 5,010 | 6.7% | 78 |
| 15.1 | 100,000 | 5,010 | 5.0% | 104 |
| 30 | 50,000 | 2,018 | 4.0% | 112 |
| 30 | 75,000 | 2,018 | 2.7% | 168 |
| 30 | 100,000 | 2,018 | 2.0% | 225 |
| 7.6 | 50,000 | 20,040 | 40.1% | 13 |
| 7.6 | 75,000 | 20,040 | 26.7% | 20 |
| 7.6 | 100,000 | 20,040 | 20.0% | 27 |

The second column is the resolution of the control, the last is how many
such moves the annual turnover cap funds. Where the first is large the signal
cannot be expressed as a small adjustment; where the last is small the budget,
not the gate, is binding.

## D. Least executable instruments (30 bp, 10 %/sleeve)

