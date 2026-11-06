| cell | intents | below | share | median intent | median/bound | entry cash | post-entry intents | fills | codes |
|---|---|---|---|---|---|---|---|---|---|
| nav120000_tol15.1_measured | 96 | 61 | 0.6354 | 2490.1 | 0.679 | 0.0326 | 89 | 22 | 7 |
| nav200000_tol15.1_measured | 101 | 57 | 0.5644 | 3375.0 | 0.920 | 0.0094 | 93 | 30 | 8 |
| nav250000_tol15.1_measured | 101 | 56 | 0.5545 | 3168.3 | 0.863 | 0.0387 | 93 | 32 | 8 |

maintenance regime only (session != 0):

- nav120000_tol15.1_measured: n=89 fills=22 below=61 share=0.6854 median=2112.2 ratio=0.576 build: n=7 below_share=0.0000 median=5824.8
- nav200000_tol15.1_measured: n=93 fills=30 below=57 share=0.6129 median=2821.0 ratio=0.769 build: n=8 below_share=0.0000 median=9812.0
- nav250000_tol15.1_measured: n=93 fills=32 below=56 share=0.6022 median=2676.0 ratio=0.729 build: n=8 below_share=0.0000 median=12265.0

verdict: {"nav120000_tol15.1_measured": {"C1_refuted": false, "C2_measured": false, "C3_composition_effect": false, "share": 0.6854, "median_cny": 2112.2, "median_over_bound": 0.576}, "nav200000_tol15.1_measured": {"C1_refuted": false, "C2_measured": false, "C3_composition_effect": false, "share": 0.6129, "median_cny": 2821.0, "median_over_bound": 0.769}, "nav250000_tol15.1_measured": {"C1_refuted": false, "C2_measured": false, "C3_composition_effect": false, "share": 0.6022, "median_cny": 2676.0, "median_over_bound": 0.729}}
