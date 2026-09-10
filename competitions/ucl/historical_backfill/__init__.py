"""Historical UCL backfill (2019/20 - 2023/24).

Reproducible, provenance-stamped ingestion of completed UCL seasons into
the leak-free historical harness format. The generated dataset lives under
``competitions/ucl/data/historical/`` (git-tracked).

Sources (all prebuilt, no live scraping):
- fixtures/results/rounds: openfootball/champions-league ``cl.txt`` (CC0)
- market odds (1X2, closing): v-eatpizzanot/soccer-dataset (CC-BY-4.0)
- Elo snapshots: xgabora Club-Football-Match-Data ``EloRatings.csv`` (MIT,
  ClubElo-derived archive snapshots strictly before each season's kickoff)
"""