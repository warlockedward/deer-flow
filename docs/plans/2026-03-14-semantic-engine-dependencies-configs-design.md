# Design Doc: Semantic Engine Dependencies & Industry Configs

**Date:** 2026-03-14
**Status:** Implemented（docs updated to match current code）  
**Topic:** Dependencies + Industry Configs (Industry Maps)

## Overview
该设计覆盖 Semantic Growth Engine 的基础依赖与行业配置（industry maps）落点，使诊断链路具备：

- 配置驱动因果推断（pgmpy）
- 可扩展行业基准与规则（industry_maps/*.json）
- 可用的解析与外联依赖（readability、markdown 转 Slack mrkdwn）

## Architecture
- **Dependency Management:** `uv` is used for backend dependency management.
- **Configuration:** JSON files stored in `backend/src/config/industry_maps/` will be used by Sensor and Interpreter agents.

## Components
### 1. Backend Dependencies
- **Libraries (关键)：**
  - `pgmpy`：贝叶斯推断与因果推断底座
  - `readabilipy`：网页正文抽取（提升信号质量）
  - `markdown-to-mrkdwn`：Markdown → Slack mrkdwn（用于消息渠道适配）
  - `langchain` / `langchain-core`：模型与工具调用框架
- **Action:** 维护 `backend/pyproject.toml` 并运行 `uv sync`。

### 2. Industry Maps
- **Location:** `backend/src/config/industry_maps/`
- **Files:**
    - `traditional_manufacturing.json`
    - `high_tech.json`
- **Schema (现行摘要)：**
  - `industry`
  - `benchmarks`
  - `industry_mapping` / `logic_mapping`
  - `signals`（time-decay / multi-source）
  - `confidence`（circuit breaker）
  - `failure_boundaries` / `policy_shock` / `trigger_rules`
  - `causal_relationships` / `conflict_rules`

## Data Flow
1. Agents (Sensor/Interpreter) read JSON configs from the industry maps directory.
2. Configs provide benchmarks for comparison and rules for detecting hedging.
3. `pgmpy` is used to perform inference based on detected symptoms and behaviors.

## Testing
- Verify `uv sync` completes without errors.
- Verify JSON files are valid and correctly placed.
 - Run backend tests covering config loading and v2 inference.

## Implementation Plan
1. Modify `backend/pyproject.toml` to add `pgmpy`.
2. Run `uv sync` in `backend/`.
3. Create `backend/src/config/industry_maps/` directory.
4. Create `traditional_manufacturing.json` and `high_tech.json`.
5. Commit changes.
