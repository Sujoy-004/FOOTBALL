# Phase 4 Discussion Log

**Date:** 2026-06-28
**Status:** Complete — all decisions captured

## Areas Discussed

### 1. BSD API Integration Strategy
- **Options presented:** Standalone fetcher script vs CLI `--validate` flag
- **User selected:** CLI `--validate` flag
- **Follow-up 1:** Validation output format — stdout summary table + enriched JSON
- **Follow-up 2:** Validation scope — both match outcomes AND market odds

### 2. Accuracy Metrics Extraction
- **Options presented:** Extract to football_core vs import from WC via sys.path
- **User selected:** Extract to `football_core/evaluation.py`
- **Follow-up:** Update WC to import from football_core — Yes

### 3. Performance Benchmark Format
- **Options presented:** Standalone script vs pytest-benchmark
- **User selected:** Standalone script (matching WC pattern)
- **Follow-up:** Time-only metrics (1K/10K/50K iterations)

### 4. Official Fixture Schedule
- **Options presented:** Require official fixtures vs synthetic + documented limitation
- **User selected:** Synthetic schedule + documented limitation

## Deferred Ideas
- Memory profiling and iteration variance — enhancement if wall-clock benchmarks show no issues
