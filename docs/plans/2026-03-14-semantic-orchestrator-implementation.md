# Semantic Orchestrator Implementation Notes (Aligned with Current Code)

**Date**: 2026-03-14  
**Status**: Implemented（本文档更新为“按现状可二次开发”的落地说明）  
**Goal**: 将 Semantic Growth Engine 的多子代理诊断链路“确定性编排 + 可审计 + 可 API 化 + 可 HITL”。

## 当前实现形态

本版本的“Semantic Orchestrator”主要由**后端确定性管线**承担，而不是依赖 `task()` 工具在对话中临时拼装链路。

### 核心文件

- **确定性管线**：`backend/src/subagents/semantic_diagnosis_pipeline.py`
  - `run_semantic_diagnosis_pipeline(...)`：串联 subagents、硬门禁、审计、产出 review_packet/drafts/outreach_plan
  - HITL 任务存储与操作：`get_hitl_task / list_hitl_tasks / claim_hitl_task / resolve_hitl_task`
- **工具入口（供 lead_agent 调用）**：`backend/src/tools/builtins/bayesian_inference.py`
  - `run_semantic_diagnosis(...)`：从 runtime 获取 thread_id/model_name 并调用管线
- **子代理配置**：`backend/src/subagents/builtins/semantic_engine.py`
  - `sensor_agent / interpreter_agent / modeler_agent / anomaly_detection_agent / composer_agent / distribution_agent`
- **HTTP API**：`backend/src/gateway/routers/diagnosis.py`
  - `POST /api/diagnosis/run`
  - HITL 任务管理 `/api/diagnosis/hitl/tasks/*`

## 扩展指南（二次开发常见改动点）

### 1) 新增/替换一个管线阶段（subagent）

目标：加入一个新的 `xxx_agent`（例如“行业政策解读 agent”）并把输出写入 `review_packet`。

建议步骤（以现有模式为准）：

1. 在 `backend/src/subagents/builtins/semantic_engine.py` 增加 `SubagentConfig`
2. 在 `backend/src/subagents/builtins/__init__.py` 注册到 `BUILTIN_SUBAGENTS`
3. 在 `backend/src/subagents/semantic_diagnosis_pipeline.py`：
   - 构造 prompt（推荐 JSON only）
   - `runner.run(subagent_name="xxx_agent", ...)` 并通过 `_parse_json(...)` 解析
   - 规范化后写入 `out[...]` 以及（如需要）`review_packet[...]`
4. 在 `backend/tests/test_semantic_diagnosis_pipeline.py` 增加 FakeRunner 场景与断言

### 2) 调整行业配置 schema

行业配置位于 `backend/src/config/industry_maps/{industry}.json`，目前管线与工具依赖的关键字段包括：

- `signals.decay_rate_months` / `signals.multi_source_threshold`
- `benchmarks`、`industry_mapping`、`logic_mapping`
- `confidence`（circuit breaker 的门槛与维度映射）
- `failure_boundaries.B`（Boundary B 环境事件确认规则）
- `policy_shock` + `trigger_rules`（policy shock mode 的 pivot 行为）
- `causal_relationships` / `conflict_rules`

更改 schema 后必须同步：

- `backend/src/tools/builtins/bayesian_inference.py` 的 `load_industry_config(...)` 及使用方
- `backend/src/subagents/semantic_diagnosis_pipeline.py` 对应字段的读取与容错
- 覆盖相关测试用例

### 3) 调整产出结构（review_packet/drafts/outreach_plan）

`review_packet` 与 `drafts` 是下游系统（UI/外联工具/存储）最常用的稳定接口。

修改建议：

- 新增字段：优先新增而不是改名/删除旧字段
- 变更字段语义：同步更新 `distribution_agent` 的输入与输出归一化逻辑
- 保持 `outreach_plan` 的 schema 可序列化且 JSON only

## 验证命令

后端验证以当前项目脚本为准：

```bash
cd backend
ruff check .
pytest -q
```
