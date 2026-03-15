# Design Document: Semantic Growth Engine V2

**Date**: 2026-03-14  
**Status**: Implemented（docs updated to match current code）  
**Topic**: Advanced Causality + Confidence Gate + Policy Shock / Failure Boundaries

## 1. Overview
V2 在“配置驱动的因果推断”基础上，补齐了生产可用的门禁与突变处理能力，使诊断链路更可控、更可审计、更适合二次开发：

- **时间衰减**与**多源验证**（降低过期/单源噪声）
- **配置驱动 DAG / causal_relationships**（支持行业差异化因果边）
- **conflict_rules 增强**（severity + trigger_signals）
- **Confidence Gate（circuit breaker）**：稀疏/单维度/基准无差异时强制降级
- **Failure Boundary B + Policy Shock Mode**：政策/环境突变触发人工复核（HITL），通过后进入 pivot 推理链
- **Distribution 产物**：human-send-only 外联方案（不发送，只产出计划）

## 2. Architecture & Data Flow
引擎由确定性管线串联多个 subagent（LangGraph/runner 承载执行）：

1. **Sensor**：读取行业 map + 抽取信号（含 source/timestamp）+ 环境事件（Boundary B）+ benchmark 偏离
2. **Interpreter**：基于 `conflict_rules` 输出冲突与症状
3. **Modeler + Tools**：根据 `causal_relationships` / verified symptoms 进行推断，并计算 `circuit_breaker`
4. **Anomaly Detection**：生成 override 建议，便于顾问封口/补丁
5. **Composer**：生成 briefing + drafts
6. **Distribution**：生成 human-send-only outreach_plan

## 3. Component Design

### 3.1 Industry Map Schema（现行）

行业配置位置：`backend/src/config/industry_maps/*.json`

关键字段：

- `signals.decay_rate_months` / `signals.multi_source_threshold`
- `causal_relationships[]`：`cause/effect/strength`
- `conflict_rules[]`：`claim/behavior/severity/trigger_signals/symptom_output`
- `confidence`：门禁阈值与维度覆盖（用于 circuit breaker）
- `failure_boundaries.B`：Boundary B 触发条件（min_sources/min_confidence/environment_signal_names）
- `policy_shock` + `trigger_rules`：shock mode 的 pivot（inference_chain/action_script）
- 兼容保留：`benchmarks`、`industry_mapping`、`logic_mapping`

### 3.2 Bayesian / Confidence Engine（工具层）

位置：`backend/src/tools/builtins/bayesian_inference.py`

- **Dynamic Construction**：按行业配置动态构造/解释因果边
- **Strength Mapping**：将 `strong/medium/weak` 映射到推断参数
- **Time Decay**：按 `decay_rate_months` 对信号置信度做衰减
- **Multi-source Verification**：按 `multi_source_threshold` 做多源确认
- **Circuit Breaker**：输出 `allow_briefing=false` 的原因清单（TOO_SPARSE / SINGLE_DIMENSION / BELOW_CONFIDENCE_THRESHOLD 等）

### 3.3 Subagents（Prompt 与角色）

位置：`backend/src/subagents/builtins/semantic_engine.py`

- **Sensor**：输出结构化 signals（含来源/时间戳）+ benchmark 偏离 + env events
- **Interpreter**：读取 `conflict_rules`，并输出 severity 与触发证据
- **Modeler**：调用工具进行推断与门禁判定，并生成可审计的 reasoning
- **Anomaly Detection**：对结论进行反模板化复核，给出 override 建议
- **Composer**：把诊断转成 briefing + drafts（价值优先，避免销售话术）
- **Distribution**：从 review_packet/drafts 生成 outreach_plan（human-send-only）

## 4. Implementation Plan Summary
V2 的落地对应到当前代码的主要改动面：

1. 行业配置 schema 扩展（industry_maps）
2. 工具层支持：动态因果 + time-decay + multi-source + circuit breaker
3. 管线层支持：Boundary B + HITL + policy shock pivot + distribution 产物
4. Subagent prompt 对齐结构化输入/输出
