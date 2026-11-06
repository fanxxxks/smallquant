# Execution cost: what could be measured, and what could not

Instruments 15 (11 tradable); excluded days (|pct_chg| > 
3.0%): 1253.

## 1. The bar-based estimators fail here — recorded, not used

- Corwin-Schultz clamped one-way median on the tradable set: **8.685 bp**,
  with **47%** of two-day pairs negative (the estimator's
  low-spread floor). It cannot resolve a spread this small.
- Roll is defined on **4/11** tradable codes; price changes
  are drift-dominated, so the bid-ask autocovariance is usually non-negative.
- Verdict: estimators failed = **True**. Daily bars do not price this.

## 2. The tick floor — measured, not assumed

Quoted step 0.001 CNY → half a tick costs `500 x 0.001 / price` bp one way.
On the tradable set that is **2.652 – 7.502 bp** all-in
(commission 2.5 + transfer 0.01 + half tick), with a maximum half-tick of 4.902 bp.

A one-way cost of 1 bp is reachable on any tradable code: **True**.
The 7.6 bp rate infimum is therefore not a modelling artefact — half of it is the
exchange's own price grid on the cheap ETFs, which are exactly the ones a 50 k account can hold.

## 3. Gate sensitivity over the reachable range

| scenario                   |   half_spread_bp |   infimum_bp |   min_order_7.6bp |   min_order_10bp |   min_order_15.1bp |
|:---------------------------|-----------------:|-------------:|------------------:|-----------------:|-------------------:|
| measured_tick_floor_min    |            2.652 |        5.252 |           19986.8 |          10200   |            5000    |
| measured_tick_floor_max    |            7.502 |       10.102 |             nan   |            nan   |            6668.45 |
| tick_floor_plus_2bp_impact |            9.502 |       12.102 |             nan   |            nan   |            9094.22 |
| inherited_5bp              |            5     |        7.6   |             nan   |          10204.1 |            5000    |
| optimistic_1bp             |            1     |        3.6   |           19986.8 |          10200   |            5000    |

## Per instrument

|   code |   obs |   excluded_days |    price |   cs_oneway_bp |   cs_negative_share |   roll_oneway_bp |   half_tick_bp |   tick_floor_bp | name       | sleeve    | tradable   |
|-------:|------:|----------------:|---------:|---------------:|--------------------:|-----------------:|---------------:|----------------:|:-----------|:----------|:-----------|
| 159915 |  2985 |             372 |   1.959  |         24.249 |               0.464 |           62.759 |          2.552 |           5.152 | 创业板ETF     | equity    | True       |
| 159920 |  3262 |              96 |   1.262  |         12.021 |               0.544 |            8.739 |          3.962 |           6.562 | 恒生ETF      | overseas  | True       |
| 159934 |  3084 |              48 |   3.5515 |          3.836 |               0.692 |          nan     |          1.408 |           4.008 | 黄金ETF(易方达) | commodity | True       |
| 510300 |  3227 |             131 |   3.866  |         16.409 |               0.447 |          nan     |          1.293 |           3.893 | 沪深300ETF   | equity    | True       |
| 510500 |  3110 |             201 |   6.159  |         18.449 |               0.46  |           50.849 |          0.812 |           3.412 | 中证500ETF   | equity    | True       |
| 511010 |  3307 |               0 | 119.574  |          2.188 |               0.436 |          nan     |          0.042 |           2.642 | 国债ETF      | bond      | False      |
| 511220 |  2880 |               1 |  95.325  |          2.72  |               0.405 |          nan     |          0.052 |           2.652 | 城投债ETF     | bond      | True       |
| 511260 |  2229 |               0 | 117.102  |          2.195 |               0.465 |          nan     |          0.043 |           2.643 | 十年国债ETF    | bond      | False      |
| 511380 |  1591 |               4 |  11.298  |          8.685 |               0.472 |          nan     |          0.443 |           3.043 | 转债ETF      | bond      | True       |
| 511880 |  3286 |               5 | 101.189  |          0.148 |               0.633 |          nan     |          0.049 |           2.649 | 银华日利       | cash      | False      |
| 511990 |  3342 |               0 | 100.002  |          0.155 |               0.487 |            0.893 |          0.05  |           2.65  | 华宝添益       | cash      | False      |
| 512100 |  2288 |             139 |   1.02   |         20.07  |               0.458 |          nan     |          4.902 |           7.502 | 中证1000ETF  | equity    | True       |
| 513100 |  3129 |             145 |   1.65   |          5.104 |               0.716 |           46.101 |          3.03  |           5.63  | 纳指ETF      | overseas  | True       |
| 513500 |  3044 |              66 |   1.681  |          5.437 |               0.674 |          nan     |          2.974 |           5.574 | 标普500ETF   | overseas  | True       |
| 518880 |  3180 |              45 |   3.522  |          3.02  |               0.715 |          nan     |          1.42  |           4.02  | 黄金ETF      | commodity | True       |
