# Design Doc: Industry Map V2 Schema Migration

## Overview
Update industry configuration JSON files to the V2 schema for the Semantic Growth Engine. This migration adds support for signal decay, multi-source thresholds, and causal relationships in the Bayesian inference engine.

## Proposed Changes

### 1. Schema Updates
Update `traditional_manufacturing.json` and `high_tech.json` to include:
- `signals`: `decay_rate_months` and `multi_source_threshold`.
- `causal_relationships`: Array of cause-effect pairs with strength indicators.
- `conflict_rules`: Enhanced with `severity` and `trigger_signals`.

### 2. Preservation
- **CRITICAL**: Preserve existing `benchmarks` values for each industry.

## Verification Plan
- Run `cd backend && python -m pytest tests/ -x -q 2>&1 | tail -5` to ensure no regressions in the Bayesian engine.
