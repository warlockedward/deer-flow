# Semantic Engine Dependencies & Industry Configs Implementation Plan

**Date**: 2026-03-14  
**Status**: Implemented（docs updated to match current code and configs）  
**Goal:** 记录后端依赖与行业配置的落地位置与现状，便于二次开发扩展。

**Architecture:** 后端通过 `uv` 管理依赖，行业配置以 JSON 形式存储在 `backend/src/config/industry_maps/`，被确定性诊断管线与 subagents/tooling 消费。

**Tech Stack:** Python, `uv`, JSON.

---

## Dependencies（现行）

依赖来源：`backend/pyproject.toml`

关键依赖（与当前链路直接相关）：

- `pgmpy`：贝叶斯推断与因果推断底座（v2 工具与推断链路依赖）
- `readabilipy`：网页正文抽取（提升信号质量）
- `markdown-to-mrkdwn`：Markdown → Slack mrkdwn（渠道适配/外联格式）
- `langchain` / `langchain-core`：模型与工具调用框架（runner/agent harness）

安装方式：

```bash
cd backend
uv sync
```

## Industry Maps（现行）

配置目录：`backend/src/config/industry_maps/`

当前已包含（至少）：

- `traditional_manufacturing.json`
- `high_tech.json`

Schema 摘要（以当前 `traditional_manufacturing.json` 为准）：

- `benchmarks`：行业 KPI 基准
- `industry_mapping` / `logic_mapping`：基准偏离与逻辑放大
- `signals.decay_rate_months` / `signals.multi_source_threshold`
- `confidence`：circuit breaker 门禁参数
- `failure_boundaries.B`：Boundary B 触发配置
- `policy_shock` + `trigger_rules`：shock mode 的 pivot 行为
- `causal_relationships` / `conflict_rules`

## 验证命令

```bash
cd backend
pytest -q
```
