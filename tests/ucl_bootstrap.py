"""Root-level UCL bootstrap helper for tests that need a complete runtime data dir.

This module provides a function to materialize a complete UCL data directory
from tracked bootstrap inputs (fixtures.json + both bootstraps + aliases +
templates) into a temporary directory. Used by root-level tests that need
guaranteed-complete stores without relying on developer-private gitignored
runtime files.
"""

import json
import shutil
from pathlib import Path


def make_ucl_runtime_dir(tmp_path: Path) -> Path:
    """Create a complete UCL runtime data dir in tmp_path/data.

    Copies tracked files from the repo into the temp directory and initializes
    empty runtime stores. Returns the path to the data directory.
    """
    repo_root = Path(__file__).resolve().parent.parent
    repo_data = repo_root / "competitions" / "ucl" / "data"
    runtime_dir = tmp_path / "data"
    runtime_dir.mkdir(parents=True)

    # Copy tracked bootstrap files
    bootstrap_src = repo_data / "bootstrap"
    bootstrap_dst = runtime_dir / "bootstrap"
    bootstrap_dst.mkdir(parents=True)
    shutil.copy(bootstrap_src / "2025_26_knockout_results.json",
                bootstrap_dst / "2025_26_knockout_results.json")
    shutil.copy(bootstrap_src / "league_results_2025_26.json",
                bootstrap_dst / "league_results_2025_26.json")

    # Copy fixtures and templates
    shutil.copy(repo_data / "fixtures.json", runtime_dir / "fixtures.json")
    shutil.copy(repo_data / "playoff_pairings.json", runtime_dir / "playoff_pairings.json")
    shutil.copy(repo_data / "bracket_rules.json", runtime_dir / "bracket_rules.json")
    shutil.copy(repo_data / "team_aliases.json", runtime_dir / "team_aliases.json")

    # Initialize empty runtime stores
    (runtime_dir / "results.json").write_text('{"matches": []}', encoding="utf-8")
    (runtime_dir / "knockout_results.json").write_text('{"matches": {}}', encoding="utf-8")

    return runtime_dir


def backfill_ucl_runtime_dir(data_dir: Path) -> None:
    """Run both KO and league backfill on a runtime data directory."""
    from competitions.ucl.backfill import run_backfill
    run_backfill(data_dir, league=False)
    run_backfill(data_dir, league=True)


def verify_gitignore_excludes_runtime() -> bool:
    """Assert that .gitignore still excludes runtime stores.

    Returns True if the key runtime files are gitignored, False otherwise.
    """
    repo_root = Path(__file__).resolve().parent.parent
    gitignore_path = repo_root / ".gitignore"
    if not gitignore_path.exists():
        return False

    content = gitignore_path.read_text(encoding="utf-8")
    # Check that the key runtime stores are excluded
    required_patterns = [
        "competitions/ucl/data/results.json",
        "competitions/ucl/data/knockout_results.json",
        "competitions/ucl/data/snapshot.json",
        "competitions/ucl/data/seasons/",  # new season stores
    ]
    for pattern in required_patterns:
        if pattern not in content:
            return False
    return True


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = make_ucl_runtime_dir(Path(tmp))
        print(f"Created runtime dir: {data_dir}")
        print(f"Files: {list(data_dir.iterdir())}")
        backfill_ucl_runtime_dir(data_dir)
        print("Backfill complete")
        print(f"results.json: {(data_dir / 'results.json').exists()}")
        print(f"knockout_results.json: {(data_dir / 'knockout_results.json').exists()}")
        print(f"gitignore check: {verify_gitignore_excludes_runtime()}")