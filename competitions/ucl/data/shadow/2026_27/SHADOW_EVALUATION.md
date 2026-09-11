# Shadow Evaluation — UCL 2026/27

- model version: `shadow-1.0.0`
- fixtures in store: 144
- results attached: 11
- prediction records: 357
- scored fixtures: 0
- pending fixtures: 119

## Segment: all (n=0)

| strategy | n | log_loss | brier | ece |
|---|---:|---:|---:|---:|
| market_elo_equal | 0 |  |  |  |
| market_elo_prior | 0 |  |  |  |
| production | 0 |  |  |  |

## Segment: odds_available (n=0)

| strategy | n | log_loss | brier | ece |
|---|---:|---:|---:|---:|
| market_elo_equal | 0 |  |  |  |
| market_elo_prior | 0 |  |  |  |
| production | 0 |  |  |  |

## Segment: odds_unavailable (n=0)

| strategy | n | log_loss | brier | ece |
|---|---:|---:|---:|---:|
| market_elo_equal | 0 |  |  |  |
| market_elo_prior | 0 |  |  |  |
| production | 0 |  |  |  |

## Paired comparisons (95% paired bootstrap)

| comparison | n | mean_delta_ll | ci95 | verdict |
|---|---:|---:|---|---|
| market_elo_equal_vs_market_elo_prior | 0 |  | — | insufficient_evidence (n=0) |
| market_elo_equal_vs_production | 0 |  | — | insufficient_evidence (n=0) |
| market_elo_prior_vs_production | 0 |  | — | insufficient_evidence (n=0) |

## Model / config version

| strategy | weights_file | weights_hash |
|---|---|---|
| market_elo_equal | None | sha256:def977608a0398066c91f4c6ce27e89f5960327d90b553e03fb0449f5a623cdd |
| market_elo_prior | market_elo_prior_weights.json | sha256:def977608a0398066c91f4c6ce27e89f5960327d90b553e03fb0449f5a623cdd |
| production | signal_weights.json | sha256:bb70bdb4587ce39266843d7a4e057ea1140dd8740829309a97726460e8539425 |
