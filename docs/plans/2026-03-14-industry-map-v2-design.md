# Design Doc: Industry Map V2 Schema Migration

**Date**: 2026-03-14  
**Status**: Implemented（docs updated to match current config schema）  

## Overview
对 `backend/src/config/industry_maps/*.json` 进行 V2 schema 对齐，使行业配置同时支撑：

- time-decay 与 multi-source verification
- 配置驱动因果边（causal_relationships）与冲突规则（conflict_rules）
- confidence gate（circuit breaker）
- Failure Boundary B 与 policy shock mode（触发 HITL 与推理链 pivot）

## Proposed Changes

### 1. Schema Updates
Update `traditional_manufacturing.json` and `high_tech.json` to include:
- `signals`: `decay_rate_months` and `multi_source_threshold`.
- `causal_relationships`: Array of cause-effect pairs with strength indicators.
- `conflict_rules`: Enhanced with `severity` and `trigger_signals`.
Additional implemented fields (required by current pipeline/tooling):
- `confidence`: thresholds + dimension coverage for circuit breaker
- `failure_boundaries`: Boundary B trigger config (min_sources/min_confidence/environment_signal_names)
- `policy_shock` + `trigger_rules`: pivot behavior when Boundary B is approved

### 2. Preservation
- **CRITICAL**: Preserve existing `benchmarks` values for each industry.
 - Preserve existing `industry_mapping` / `logic_mapping` values if present (used for benchmark deviation amplification).

## Verification Plan
- Run `cd backend && pytest -q` to ensure no regressions in config loading and v2 inference.
