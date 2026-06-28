{
  "audit_meta": {
    "phase": "02-ucl-knockout-phase",
    "reviewed": "2026-06-28",
    "auditor": "gsd-code-reviewer (deep analysis)",
    "status": "issues_found"
  },
  "audit_1_public_api_freeze": {
    "status": "PASS",
    "details": {
      "new_public_functions": {
        "simulate_two_legged_tie": {
          "file": "competitions/ucl/src/knockout.py",
          "line": 85,
          "signature": "simulate_two_legged_tie(team_a: str, team_b: str, elo_ratings: dict[str, float], rng: random.Random, base_rate: float = ..., et_lambda_factor: float = 0.25, penalty_conversion_rate: float = 0.76) -> dict",
          "exported_from_init": true,
          "signature_stable": true,
          "docstring_describes_contract": true
        },
        "simulate_playoff_round": {
          "file": "competitions/ucl/src/knockout.py",
          "line": 215,
          "signature": "simulate_playoff_round(standings: list[dict], elo_ratings: dict[str, float], rng: random.Random, playoff_pairings_path: str | None = None, base_rate: float = ..., et_lambda_factor: float = 0.25, penalty_conversion_rate: float = 0.76) -> dict",
          "exported_from_init": true,
          "signature_stable": true,
          "docstring_describes_contract": true,
          "notes": "playoff_pairings_path defaults to None (internal file discovery). Acceptable for test injection; not confusing to callers who omit it."
        },
        "build_r16_bracket": {
          "file": "competitions/ucl/src/knockout.py",
          "line": 463,
          "signature": "build_r16_bracket(standings: list[dict], playoff_results: dict, bracket_rules_path: str | None = None) -> dict",
          "exported_from_init": true,
          "signature_stable": true,
          "docstring_describes_contract": true,
          "notes": "bracket_rules_path defaults to None (internal file discovery). Same pattern as simulate_playoff_round."
        },
        "simulate_knockout_tree": {
          "file": "competitions/ucl/src/knockout.py",
          "line": 588,
          "signature": "simulate_knockout_tree(bracket: dict, elo_ratings: dict[str, float], rng: random.Random, base_rate: float = ..., et_lambda_factor: float = 0.25, penalty_conversion_rate: float = 0.76) -> dict",
          "exported_from_init": true,
          "signature_stable": true,
          "docstring_describes_contract": true
        },
        "track_knockout_stages": {
          "file": "competitions/ucl/src/knockout.py",
          "line": 711,
          "signature": "track_knockout_stages(standings: list[dict], knockout_result: dict) -> dict[str, str]",
          "exported_from_init": true,
          "signature_stable": true,
          "docstring_describes_contract": true
        }
      },
      "private_functions_not_exported": {
        "_simulate_penalty_shootout": {"file": "knockout.py", "line": 42, "not_exported": true},
        "_simulate_single_knockout_match": {"file": "knockout.py", "line": 366, "not_exported": true},
        "_validate_bracket_entry": {"file": "knockout.py", "line": 436, "not_exported": true}
      },
      "phase1_functions_extended": {
        "aggregate_mc_results": {
          "file": "simulation.py",
          "line": 108,
          "note": "Extended with optional stage_collectors param. Backward compatible.",
          "exported_from_init": true
        },
        "run_monte_carlo": {
          "file": "simulation.py",
          "line": 182,
          "note": "Extended with knockout pipeline integration. Returns stage_order metadata.",
          "exported_from_init": true
        }
      }
    },
    "findings": [],
    "verdict": "All 5 new public functions are exported from __init__.py. Signatures are stable with documented contracts. No TODO params, no star-import leaks. PASS."
  },
  "audit_2_dependency": {
    "status": "WARN",
    "details": {
      "circular_imports": {
        "result": "PASS",
        "evidence": "Import graph: simulation.py → groups.py → football_core; simulation.py → knockout.py → football_core; elo_fetcher.py → football_core. No cycles detected.",
        "graph": "simulation.py -> groups.py -> football_core; simulation.py -> knockout.py -> football_core; elo_fetcher.py -> football_core"
      },
      "duplicate_implementations": {
        "result": "PASS",
        "evidence": "No true duplicate function bodies found. The Poisson scoring pattern (_build_poisson_table + getrandbits) is intentionally shared from football_core across groups.py and knockout.py — correct per D-11 (no core modifications). The file-path-discovery glob pattern (glob.glob + os.path.join) is independently repeated in simulate_playoff_round (knockout.py:265-274) and build_r16_bracket (knockout.py:505-514) — minor style concern but not functional duplication. Test fixtures in conftest.py mirror this pattern — acceptable for test isolation."
      },
      "dead_code": {
        "result": "PASS",
        "evidence": "All defined symbols in knockout.py are referenced: _simulate_penalty_shootout (called at lines 179, 414), _simulate_single_knockout_match (called at line 653), _validate_bracket_entry (called at line 521), _DEFAULT_BRACKET_FILENAME (referenced at line 513). All imports (glob, json, os, random, football_core.*) are used. In simulation.py, STAGE_ORDER (referenced at line 302), STAGE_TO_VALUE (referenced at line 289) are both used."
      },
      "unused_json_files": {
        "result": "PASS",
        "evidence": "playoff_pairings.json: read by simulate_playoff_round() at knockout.py:276-278. bracket_rules.json: read by build_r16_bracket() at knockout.py:516-517. Both files are consumed by production code."
      },
      "unreachable_tests": {
        "result": "WARN",
        "findings": [
          {
            "severity": "WARNING",
            "id": "WR-01",
            "file": "competitions/ucl/tests/test_knockout.py",
            "lines": [5, 445, 453, 461, 472, 485],
            "issue": "Redundant `import random` statement repeated inside 5 test methods (lines 445, 453, 461, 472, 485) when `random` is already imported at module level (line 5). This shadows the module-level import and creates unnecessary re-import overhead. Also, line 34: test_two_legs_draw_aggregate_et_played accepts fixture `sample_rng` but never uses it (creates own rng in loop).",
            "fix": "Remove the 5 duplicate `import random` statements inside test methods. Remove unused `sample_rng` fixture from test_two_legs_draw_aggregate_et_played signature."
          }
        ],
        "test_collection_check": {
          "test_knockout.py": {
            "total_test_methods": 40,
            "all_test_methods_collectable": true,
            "conditional_skips": 0,
            "unconditional_skips": 0,
            "notes": "All 40 test methods start with `test_` prefix and are collected. No unconditional skips."
          }
        }
      }
    },
    "verdict": "No circular imports, no duplicate implementations, no dead code, both JSON files are consumed. WARN: redundant import random inside test methods (5 occurrences) and unused fixture parameter."
  },
  "audit_3_performance": {
    "status": "FAIL",
    "details": {
      "mc_loop_location": "simulation.py:255-290",
      "items": [
        {
          "check": "playoff_pairings.json loaded outside loop",
          "result": "FAIL",
          "file": "knockout.py:276-278",
          "call_site": "simulation.py:265",
          "issue": "simulate_playoff_round() opens and reads playoff_pairings.json from disk on every call via file discovery (glob + open + json.load). Called inside the MC iteration loop at simulation.py:265 without passing an explicit playoff_pairings_path, so file I/O occurs n_iterations times.",
          "fix": "Load playoff_pairings.json once before the MC loop and pass it to simulate_playoff_round() as the playoff_pairings_path argument. Or lift the JSON load out of simulate_playoff_round() into run_monte_carlo() and pass pairings data directly.",
          "evidence": "knockout.py lines 265-278: glob discovery + open + json.load; simulation.py line 265: simulate_playoff_round(standings, elo_dict, rng) — no path override → triggers file read every iteration."
        },
        {
          "check": "bracket_rules.json loaded outside loop",
          "result": "FAIL",
          "file": "knockout.py:516-517",
          "call_site": "simulation.py:268",
          "issue": "build_r16_bracket() opens and reads bracket_rules.json from disk on every call via file discovery (glob + open + json.load). Called inside the MC iteration loop at simulation.py:268 without passing an explicit bracket_rules_path, so file I/O occurs n_iterations times.",
          "fix": "Load bracket_rules.json once before the MC loop and pass it to build_r16_bracket() as the bracket_rules_path argument. Or lift the JSON load out of build_r16_bracket() into run_monte_carlo() and pass bracket data directly.",
          "evidence": "knockout.py lines 505-517: glob discovery + open + json.load; simulation.py line 268: build_r16_bracket(standings, playoff_result) — no path override → triggers file read every iteration."
        },
        {
          "check": "No other file I/O or heavy computation inside loop",
          "result": "PASS",
          "evidence": "Beyond the two JSON loads (which are the issue), the loop body is pure computation: Poisson simulation (in-memory), standings computation (in-memory), knockout tree traversal (in-memory), and list appends. No additional file I/O, no network calls, no database queries. The precomputed matchup_lambdas pattern (simulation.py:233-235) correctly caches the heavy expected_goals() computations outside the loop."
        },
        {
          "check": "Complexity confirmation",
          "result": "O(n_iterations) with 2× file I/O overhead per iteration",
          "evidence": "The MC loop is O(n) in iterations. Each iteration executes: league phase simulation (144 Poisson match draws) → standings computation → playoff round (8× two-legged ties) → bracket construction → knockout tree (15 matches). The 2x JSON file reads per iteration add unnecessary constant-factor overhead but don't change asymptotic complexity."
        }
      ]
    },
    "findings": [
      {
        "severity": "WARNING",
        "id": "WR-02",
        "file": "competitions/ucl/src/knockout.py",
        "line": "265-278",
        "issue": "playoff_pairings.json loaded from disk on every MC iteration via simulate_playoff_round(). With default n_iterations=10000, this produces 10,000 redundant disk reads.",
        "fix": "Option A: Load json once in run_monte_carlo() before the loop, pass parsed dict to simulate_playoff_round() via a new parameter or as pre-loaded data. Option B: Create a module-level cache for the data file so the second call returns instantly (e.g., functools.lru_cache on the loader). Option C: Add a `pairings_data` parameter to simulate_playoff_round() that accepts pre-loaded dict, fall back to None for file load."
      },
      {
        "severity": "WARNING",
        "id": "WR-03",
        "file": "competitions/ucl/src/knockout.py",
        "line": "505-517",
        "issue": "bracket_rules.json loaded from disk on every MC iteration via build_r16_bracket(). With default n_iterations=10000, this produces 10,000 redundant disk reads.",
        "fix": "Same pattern as playoff_pairings.json: load once before the MC loop and pass pre-loaded data to build_r16_bracket(). Add a `bracket_data` parameter that accepts pre-loaded dict, or load at the run_monte_carlo() level."
      }
    ],
    "verdict": "FAIL: Both playoff_pairings.json and bracket_rules.json are loaded from disk on every Monte Carlo iteration. This is O(n_iterations) file I/O when the data could be loaded once and reused. Fix before production deployment with n_iterations >= 10000."
  },
  "audit_4_forward_compat": {
    "status": "PASS",
    "details": {
      "stable_return_types_for_phase_3": {
        "result": "PASS",
        "evidence": "All public functions return dicts with documented key structures. simulate_two_legged_tie() returns a consistent dict schema (winner, loser, aggregate_a/b, leg1/leg2, et/penalty fields). simulate_playoff_round() returns {winners, ties, standings}. build_r16_bracket() returns {matchups, tree}. simulate_knockout_tree() returns {matchups, rounds, stage, champion}. track_knockout_stages() returns dict[str, str]. run_monte_carlo() returns {snapshot_date, n_iterations, seed, teams, stage_order}. All suitable for Phase 3 CLI formatting."
      },
      "no_confusing_internal_params": {
        "result": "PASS",
        "evidence": "playoff_pairings_path and bracket_rules_path both default to None (file auto-discovery). Phase 3 callers never need to provide these. The delay parameter in fetch_team_elos() is documented as 'Ignored (kept for backward compatibility)' — not confusing since callers never use it."
      },
      "aggregate_mc_results_stage_collectors": {
        "result": "PASS",
        "evidence": "stage_collectors parameter defaults to None. When None, stage probabilities are skipped — fully backward compatible with Phase 1. When provided, D-09 stage probabilities are computed. Verified at simulation.py line 160: `if stage_collectors and team in stage_collectors:` — safe guard."
      },
      "champion_prob_now_from_knockout": {
        "result": "PASS",
        "evidence": "simulation.py lines 286-287: `if stages[team] == \"champion\": champions[team] += 1`. Champion is determined by the knockout tree, not by league position 1. This is correct for Phase 2 semantics."
      },
      "champions_data_for_phase_3_display": {
        "result": "PASS (with note)",
        "evidence": "Per-team champion_prob is available in the teams dict output from run_monte_carlo(). The stage_order metadata field is also included. Phase 3 can display 'Champion: Man City (12.3%)' by iterating teams dict and finding max champion_prob."
      },
      "caveats_for_phase_3_consumers": [
        {
          "id": "IN-01",
          "severity": "INFO",
          "file": "competitions/ucl/src/knockout.py",
          "line": 418,
          "issue": "_simulate_single_knockout_match() returns different result schemas for final vs non-final matches. For non-finals (R16/QF/SF), it delegates to simulate_two_legged_tie() which returns {aggregate_a, aggregate_b, leg1, leg2, ...}. For the final (is_final=True), it returns {score_a, score_b, is_final=True} without leg keys. Phase 3 display code must handle both structures.",
          "fix": "Document in the function contract that final results lack aggregate/leg keys. Phase 3 should check `result.get('is_final')` or test for `'leg1' in result` before accessing leg data. Current test_knockout.py:489 already handles this: `final_result.get('is_final', False) or 'leg1' not in final_result`."
        }
      ]
    },
    "verdict": "PASS: All return types are stable and documented. stage_collectors is optional for backward compatibility. champion_prob correctly reflects knockout champion. Caveat: final match result structure differs from non-final (documented)."
  },
  "summary": {
    "audit_1": {"status": "PASS", "critical": 0, "warning": 0, "info": 0},
    "audit_2": {"status": "WARN", "critical": 0, "warning": 1, "info": 0},
    "audit_3": {"status": "FAIL", "critical": 0, "warning": 2, "info": 0},
    "audit_4": {"status": "PASS", "critical": 0, "warning": 0, "info": 1},
    "total": {"critical": 0, "warning": 3, "info": 1}
  },
  "blocking_items": [
    {
      "id": "WR-02",
      "audit": "audit_3_performance",
      "severity": "WARNING",
      "description": "playoff_pairings.json loaded from disk on every MC iteration (simulation.py:265 → knockout.py:276-278). 10,000 redundant file reads at default n_iterations.",
      "file": "competitions/ucl/src/knockout.py",
      "line": "276-278",
      "fix_summary": "Load once before MC loop; pass pre-loaded data to simulate_playoff_round()"
    },
    {
      "id": "WR-03",
      "audit": "audit_3_performance",
      "severity": "WARNING",
      "description": "bracket_rules.json loaded from disk on every MC iteration (simulation.py:268 → knockout.py:516-517). 10,000 redundant file reads at default n_iterations.",
      "file": "competitions/ucl/src/knockout.py",
      "line": "516-517",
      "fix_summary": "Load once before MC loop; pass pre-loaded data to build_r16_bracket()"
    },
    {
      "id": "WR-01",
      "audit": "audit_2_dependency",
      "severity": "WARNING",
      "description": "Redundant `import random` inside 5 test methods. Unused fixture sample_rng in one test.",
      "file": "competitions/ucl/tests/test_knockout.py",
      "lines": [5, 445, 453, 461, 472, 485],
      "fix_summary": "Remove duplicate imports; remove unused fixture param"
    }
  ],
  "info_items": [
    {
      "id": "IN-01",
      "audit": "audit_4_forward_compat",
      "severity": "INFO",
      "description": "Final match result dict lacks aggregate/leg keys that non-final results have. Phase 3 display must handle both schemas.",
      "file": "competitions/ucl/src/knockout.py",
      "line": 418
    }
  ]
}
