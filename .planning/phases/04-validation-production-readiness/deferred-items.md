# Deferred Items — Phase 4, Plan 4

## Pre-existing WC test_knockout.py path issue

**Found during:** Task 3 (WC regression verification)

**Issue:** 10 tests in `competitions/worldcup/tests/test_knockout.py` fail with `FileNotFoundError` because the test fixture uses a relative `DATA_DIR = "data"` path that referenced the old `worldcup_predictor/` directory structure. After the restructuring (commit `bb25807`) that moved WC code into `competitions/worldcup/`, these tests were not updated to use the correct path resolution.

**Affected tests:**
- 5 tests in `TestKnockoutBuildRoundMap` class
- 5 tests in `TestRunFullSimulation` class

**Not caused by Phase 4 changes** — this is a pre-existing issue from repo restructuring.
