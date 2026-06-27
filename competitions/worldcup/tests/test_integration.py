"""Integration tests for the World Cup predictor.

Verifies the end-to-end flow: seed teams → save → load → Elo update →
save → reload → data matches. This programmatically proves that Elo
ratings persist across restarts and played match records are stored
correctly.
"""

from datetime import datetime, timezone

import pytest

from src.elo import update_ratings
from src.state import load_played, load_teams, save_played, save_teams


def test_elo_update_persistence_roundtrip(tmp_path):
    """Verify full roundtrip: seed → save → load → Elo update → save → reload → assert.

    This test uses a tmp_path to avoid modifying real data files.
    It verifies that:
      1. Initial teams can be saved and loaded back identically.
      2. Elo ratings update correctly after a match result.
      3. Updated ratings persist through save → reload.
      4. Played match records persist through save → reload.
      5. Ratings differ from initial values (update actually happened).
    """
    # 1. Seed initial teams
    teams = {
        "Argentina": {"elo": 2115},
        "Nigeria": {"elo": 1770},
    }

    # 2. Save initial state to tmp_path
    save_teams(teams, data_dir=tmp_path)

    # 3. Load teams back
    loaded = load_teams(data_dir=tmp_path)
    assert loaded == teams

    # 4. Apply Elo update (Argentina beats Nigeria)
    old_arg = loaded["Argentina"]["elo"]
    old_nig = loaded["Nigeria"]["elo"]

    new_ratings = update_ratings(
        "Argentina", "Nigeria", "Argentina",
        {"Argentina": loaded["Argentina"]["elo"], "Nigeria": loaded["Nigeria"]["elo"]},
        K=60,
    )
    loaded["Argentina"]["elo"] = new_ratings["Argentina"]
    loaded["Nigeria"]["elo"] = new_ratings["Nigeria"]

    # 5. Build played record (per D-06 schema)
    played = {
        "R16_1": {
            "team_a": "Argentina",
            "team_b": "Nigeria",
            "winner": "Argentina",
            "home_score": 2,
            "away_score": 1,
            "completed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    }

    # 6. Persist updated state
    save_teams(loaded, data_dir=tmp_path)
    save_played(played, data_dir=tmp_path)

    # 7. Reload state
    reloaded_teams = load_teams(data_dir=tmp_path)
    reloaded_played = load_played(data_dir=tmp_path)

    # 8. Verify Elo persistence — updated values match
    assert reloaded_teams["Argentina"]["elo"] == new_ratings["Argentina"]
    assert reloaded_teams["Nigeria"]["elo"] == new_ratings["Nigeria"]

    # 9. Verify played record persistence
    assert reloaded_played["R16_1"]["winner"] == "Argentina"
    assert reloaded_played["R16_1"]["home_score"] == 2
    assert reloaded_played["R16_1"]["away_score"] == 1

    # 10. Verify teams changed from initial values
    assert reloaded_teams["Argentina"]["elo"] != old_arg
    assert reloaded_teams["Nigeria"]["elo"] != old_nig
