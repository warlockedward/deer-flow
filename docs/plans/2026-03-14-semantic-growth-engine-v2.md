# Semantic Growth Engine V2 Implementation Notes (Aligned with Current Code)

**Date**: 2026-03-14  
**Status**: Implemented（本文档更新为“按现状可二次开发”的落地说明）  
**Goal**: 在配置驱动的因果推断基础上，落地 time-decay、多源验证、动态因果边、confidence gate、Boundary B/policy shock 与外联产物。

## 落点一览（关键文件）

- 行业配置：`backend/src/config/industry_maps/*.json`
- 推断与门禁工具：`backend/src/tools/builtins/bayesian_inference.py`
- 子代理 prompts：`backend/src/subagents/builtins/semantic_engine.py`
- 确定性管线（编排 + HITL + 审计 + 产物）：`backend/src/subagents/semantic_diagnosis_pipeline.py`
- 测试：
  - `backend/tests/tools/test_bayesian_inference_v2.py`
  - `backend/tests/test_semantic_engine_v2.py`
  - `backend/tests/test_semantic_diagnosis_pipeline.py`
  - `backend/tests/test_industry_override_loading.py`

## Industry Map V2（当前 schema 摘要）

以 `traditional_manufacturing.json` 为例，V2 关键字段包括：

- `signals.decay_rate_months` / `signals.multi_source_threshold`
- `causal_relationships[]`：`cause/effect/strength`
- `conflict_rules[]`：`claim/behavior/severity/trigger_signals/symptom_output`
- `confidence`：门禁参数（threshold/min_verified_symptoms/min_sources_total/min_dimensions/signal_dimensions 等）
- `failure_boundaries.B`：Boundary B 硬门禁触发条件
- `policy_shock` + `trigger_rules`：shock mode 的 pivot（inference_chain/action_script）
- 兼容字段：`benchmarks`、`industry_mapping`、`logic_mapping`

## 二次开发建议

### 1) 新增一个行业

1. 在 `backend/src/config/industry_maps/` 新增 `{industry}.json`（参照现有 schema）
2. 在测试中增加加载/推断覆盖（优先复用 `test_industry_override_loading.py` 的风格）

### 2) 增加一个因果边或冲突规则

1. 修改对应行业 JSON 的 `causal_relationships` / `conflict_rules`
2. 确认工具层对 strength/trigger_signals 兼容（必要时扩展映射）
3. 扩充 `test_bayesian_inference_v2.py` 与 `test_semantic_engine_v2.py`

### 3) 调整门禁策略（circuit breaker / Boundary B）

1. 修改行业 JSON 的 `confidence` 或 `failure_boundaries.B`
2. 验证 `run_semantic_diagnosis_pipeline` 在未批准 HITL 时仍能稳定输出 `pause_manifesto`

## 验证命令

```bash
cd backend
ruff check .
pytest -q
```
