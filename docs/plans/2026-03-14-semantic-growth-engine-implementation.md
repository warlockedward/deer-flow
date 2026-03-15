# Semantic Growth Engine Implementation Notes (Aligned with Current Code)

**Date**: 2026-03-14  
**Status**: Implemented（本文档更新为“按现状可二次开发”的落地说明）  
**Goal**: 实现可审计、可门禁、可 HITL 的语义诊断链路，并产出可用于外联的结构化包（review_packet/drafts/outreach_plan）。

## 入口与调用方式

- **Agent Tool 入口**：`run_semantic_diagnosis`（`backend/src/tools/builtins/bayesian_inference.py`）
- **HTTP API 入口**：`POST /api/diagnosis/run`（`backend/src/gateway/routers/diagnosis.py`）
- **核心编排管线**：`run_semantic_diagnosis_pipeline`（`backend/src/subagents/semantic_diagnosis_pipeline.py`）

## 已实现的关键模块

### 1) 行业配置（Industry Maps）

- 路径：`backend/src/config/industry_maps/*.json`
- 当前 schema（以 `traditional_manufacturing.json` 为例）：
  - `benchmarks`：行业基准 KPI
  - `industry_mapping` / `logic_mapping`：从指标偏离到逻辑放大系数
  - `signals`：`decay_rate_months`、`multi_source_threshold`
  - `confidence`：circuit breaker 参数（阈值/维度/最小覆盖）
  - `failure_boundaries.B`：Boundary B（政策/环境突变）确认规则
  - `policy_shock` + `trigger_rules`：shock mode 的 pivot 逻辑
  - `causal_relationships`、`conflict_rules`：DAG 与冲突规则（给工具/Interpreter 使用）

### 2) Hybrid Symbolic Tool（贝叶斯 + 门禁 + 反馈闭环）

- 路径：`backend/src/tools/builtins/bayesian_inference.py`
- 能力：
  - `calculate_bayesian_risk` / `diagnose_management_gap`：风险推断与门禁计算
  - `compute_circuit_breaker_state`：置信度门禁（用于 allow_briefing 决策）
  - `run_semantic_diagnosis`：工具入口（连接 lead_agent 与确定性管线）
  - `update_priors` / `store_review_record`：反馈数据落盘（后续可扩展为在线学习）

### 3) Subagents（专业节点）

- 路径：`backend/src/subagents/builtins/semantic_engine.py`
- Agents：
  - `sensor_agent`：信号采集 + benchmark + env events
  - `interpreter_agent`：冲突/症状解析
  - `modeler_agent`：RAR 反思门 + 推断结论
  - `anomaly_detection_agent`：异常与 override 建议
  - `composer_agent`：mentor briefing + drafts
  - `distribution_agent`：human-send-only 外联方案（不发送，只产出计划）

### 4) Deterministic Pipeline（把链路“连起来”的地方）

- 路径：`backend/src/subagents/semantic_diagnosis_pipeline.py`
- 关键职责：
  - 统一输入输出（JSON 可序列化）
  - 审计（audit_id + 过程落盘）
  - 硬门禁（circuit breaker / Boundary B / HITL）
  - 产物构建（review_packet/drafts/outreach_plan）

### 5) HITL 与 API 管理

- 路径：`backend/src/gateway/routers/diagnosis.py`
- 能力：
  - 运行诊断：`POST /api/diagnosis/run`
  - 任务管理：list/get/claim/resolve HITL tasks（用于顾问封口与补丁回填）

## 二次开发推荐路径

1. 先改行业配置（新增行业/扩展 schema）→ 补齐工具读取与测试
2. 再改 subagent prompt（让输出更结构化）→ 调整 pipeline 的归一化与落盘字段
3. 最后改 API schema（对外输出字段稳定）→ 增补集成测试

## 验证命令

```bash
cd backend
ruff check .
pytest -q
```
