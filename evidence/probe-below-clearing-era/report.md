# Below-clearing intents by era (E3, 50,000 CNY)

V1 reconstruction, lots arm: 49 of 65 intents below clearing, median 1888.5 CNY (target 49 of 65, 1888.5).

| arm | era | intents | below | share | median CNY |
|---|---|---|---|---|---|
| static | pooled | 102 | 96 | 0.9412 | 1573.4 |
| static | era_2016_2022 | 72 | 66 | 0.9167 | 1593.3 |
| static | era_2023_2025 | 30 | 30 | 1.0000 | 1522.5 |
| lots | pooled | 65 | 49 | 0.7538 | 1888.5 |
| lots | era_2016_2022 | 43 | 32 | 0.7442 | 1464.9 |
| lots | era_2023_2025 | 22 | 17 | 0.7727 | 2878.1 |
| lots_deploy | pooled | 67 | 44 | 0.6567 | 2456.3 |
| lots_deploy | era_2016_2022 | 45 | 29 | 0.6444 | 2456.3 |
| lots_deploy | era_2023_2025 | 22 | 15 | 0.6818 | 2353.8 |

## lots arm by year

| year | intents | below | share | median CNY |
|---|---|---|---|---|
| 2016 | 8 | 3 | 0.3750 | 4886.6 |
| 2017 | 5 | 4 | 0.8000 | 803.1 |
| 2018 | 5 | 4 | 0.8000 | 1464.9 |
| 2019 | 5 | 5 | 1.0000 | 1419.0 |
| 2020 | 6 | 4 | 0.6667 | 2129.3 |
| 2021 | 7 | 6 | 0.8571 | 534.7 |
| 2022 | 7 | 6 | 0.8571 | 925.4 |
| 2023 | 7 | 5 | 0.7143 | 1659.6 |
| 2024 | 7 | 6 | 0.8571 | 2897.1 |
| 2025 | 8 | 6 | 0.7500 | 3233.7 |

## lots arm by sleeve

| sleeve | 2016-2022 n / below / share | 2023-2025 n / below / share |
|---|---|---|
| equity | 22 / 18 / 0.8182 | 9 / 9 / 1.0 |
| bond | 6 / 2 / 0.3333 | 6 / 4 / 0.6667 |
| commodity | 8 / 7 / 0.875 | 4 / 2 / 0.5 |
| overseas | 7 / 5 / 0.7143 | 3 / 2 / 0.6667 |

## build year versus maintenance years (lots arm)

- build 2016: 3/8 = 0.3750, median 4886.6 CNY, CI95 [0.1368, 0.6943]
- maintenance 2017-2025: 46/57 = 0.8070, median 1659.6 CNY, CI95 [0.6866, 0.8887]

## verdict

- E1 delta (2023-2025 minus 2016-2022, lots arm): +0.0285, with 22 post-split intents (CI95 [0.5656, 0.8988]) against 43 (CI95 [0.5976, 0.8507]). Not detectable at this n: the intervals overlap and a 15 pp shift could not have been shown.
- M1 bond share 0.3333333333333333 -> 0.6666666666666666; largest other-sleeve move 0.3750. Not concentrated in bond: the split story does not carry it alone.
