# Expressibility at entry: at what capital does member order stop deciding?

32 recorded quarterly starts, endpoint 2026-11-04, tolerance 15.1 bp, cost measured, **entry-time only; NAV = capital, no deployment feedback**.

P0 entry closed form vs session-0 fills: 12/12 agree.

## Starts where the sleeve cannot express all its available members

| capital | equity | bond | commodity | overseas |
|---|---|---|---|---|
| 50000 | 0/32 | 11/32 | 32/32 | 32/32 |
| 60000 | 0/32 | 0/32 | 32/32 | 32/32 |
| 70000 | 0/32 | 0/32 | 32/32 | 32/32 |
| 80000 | 0/32 | 0/32 | 0/32 | 32/32 |
| 90000 | 0/32 | 0/32 | 0/32 | 32/32 |
| 100000 | 0/32 | 0/32 | 0/32 | 32/32 |
| 110000 | 0/32 | 0/32 | 0/32 | 32/32 |
| 120000 | 0/32 | 0/32 | 0/32 | 32/32 |

## How many members the sleeve actually holds (k histogram)

| capital | equity | bond | commodity | overseas |
|---|---|---|---|---|
| 50000 | {'2': 4, '3': 28} | {'1': 29, '2': 3} | {'1': 32} | {'1': 32} |
| 60000 | {'2': 4, '3': 28} | {'1': 18, '2': 14} | {'1': 32} | {'1': 32} |
| 70000 | {'2': 4, '3': 28} | {'1': 18, '2': 14} | {'1': 32} | {'1': 32} |
| 80000 | {'2': 4, '3': 28} | {'1': 18, '2': 14} | {'2': 32} | {'1': 32} |
| 90000 | {'2': 4, '3': 28} | {'1': 18, '2': 14} | {'2': 32} | {'2': 32} |
| 100000 | {'2': 4, '3': 28} | {'1': 18, '2': 14} | {'2': 32} | {'2': 32} |
| 110000 | {'2': 4, '3': 28} | {'1': 18, '2': 14} | {'2': 32} | {'2': 32} |
| 120000 | {'2': 4, '3': 28} | {'1': 18, '2': 14} | {'2': 32} | {'2': 32} |

C* per sleeve: {'equity': 33775, 'bond': 56172, 'commodity': 73390, 'overseas': 133080}
C* all sleeves: 133080

**Verdict:** venue-constraint: the last sleeve to become order-free needs 133,080 CNY, so the prefix rule binds across the whole 50-100k range.

