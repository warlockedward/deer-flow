# Design Doc: Semantic Orchestrator (Deterministic Pipeline + Tool Entry)

**Date**: 2026-03-14  
**Status**: Implemented (docs updated to match current code)  
**Topic**: The orchestration layer for the Semantic Growth Engine.

## Overview

“Semantic Orchestrator”在当前版本不再依赖单一的 `task()` 编排技能文件来串联链路，而是以**确定性的后端管线**为主（便于审计、硬门禁、HITL 任务落盘、API 化调用），并通过：

- **Agent Tool 入口**：`run_semantic_diagnosis`（供 `lead_agent` 调用）
- **Gateway API 入口**：`POST /api/diagnosis/run`（供外部系统/前端调用）

将多子代理的诊断链路打通，输出可用于二次开发的结构化结果（审计、review_packet、drafts、outreach_plan、HITL 等）。

## 关键入口

### 1) Tool 入口（供 lead_agent）

- 入口函数：`run_semantic_diagnosis(runtime, company_name, industry, hitl_approved=False, reviewer=None)`
- 位置：`backend/src/tools/builtins/bayesian_inference.py`
- 行为：从 `runtime.context` 获取 `thread_id`，从 `runtime.config.metadata` 获取 `model_name`，并调用确定性管线。

### 2) Deterministic Pipeline（核心编排）

- 入口函数：`run_semantic_diagnosis_pipeline(...)`
- 位置：`backend/src/subagents/semantic_diagnosis_pipeline.py`
- 特点：
  - 以 JSON 输入/输出串联子代理
  - 强制落审计（audit_id + jsonl）
  - 硬门禁（circuit breaker、Boundary B、HITL）
  - 固化输出字段，方便前端和后续组件消费

### 3) HTTP API（供外部调用）

- `POST /api/diagnosis/run`
- HITL 任务管理：
  - `GET /api/diagnosis/hitl/tasks`
  - `GET /api/diagnosis/hitl/tasks/{task_id}`
  - `POST /api/diagnosis/hitl/tasks/{task_id}/claim`
  - `POST /api/diagnosis/hitl/tasks/{task_id}/resolve`
- 位置：`backend/src/gateway/routers/diagnosis.py`

## 子代理与配置位置

子代理配置集中在：

- `backend/src/subagents/builtins/semantic_engine.py`

当前链路使用到的核心 subagents：

1. `sensor_agent`：读取行业配置 + 抓取公司信号 + 行业 benchmark + Boundary B 环境事件
2. `interpreter_agent`：冲突规则 + 基准偏离（benchmark deviation）→ 结构化症状/特征
3. `modeler_agent`：RAR 反思门 + 贝叶斯风险 + EMBA 锚点 +（工具层）circuit breaker
4. `anomaly_detection_agent`：反模板化复核（例外情况与 override 建议）
5. `composer_agent`：价值优先的 mentor briefing（严禁销售话术）
6. `distribution_agent`：human-send-only 外联方案（渠道/窗口/最终文案/合规护栏/追踪键）

## 管线阶段与数据流（简化）

1. 读取行业配置：`backend/src/config/industry_maps/{industry}.json`
2. `sensor_agent` → `signals + benchmarks + environment_events`
3. Boundary B 判定：
   - 若触发且未获得 HITL 批准：`allow_briefing=false` + 输出 `pause_manifesto` + 落 HITL 任务
   - 若触发且 HITL 批准：进入 policy shock mode（可对 inference_chain / action_script 进行 pivot）
4. `interpreter_agent` → `conflicts/features`
5. 计算 `circuit_breaker`（confidence gate）与 verified 症状
6. `modeler_agent` + `anomaly_detection_agent` → `sealed_review`（必要时应用 override/patch）
7. `composer_agent` → `briefing`
8. 构建 `review_packet` 与 `drafts`
9. 若 `allow_briefing=true`：`distribution_agent` → `outreach_plan`，并写入 `review_packet.distribution_bundle`

## 产物约定（供二次开发）

管线返回字典包含但不限于：

- `audit_id`、`hitl_decision`、`reasons`、`policy_shock`
- `signals`、`benchmarks`、`conflicts`、`circuit_breaker`、`anomalies`
- `sealed_review`、`review_packet`、`drafts`、`briefing`
- `outreach_plan`（可选，受门禁影响）
- `hitl_task_id`（可选，需人工复核时产生）

## 验证方式

以代码为准的验证入口：

- 单元/集成测试：`backend/tests/test_semantic_diagnosis_pipeline.py`
- API 路由测试（若需要覆盖）：`backend/tests/test_ontology_update_router.py` 等相同风格用例
