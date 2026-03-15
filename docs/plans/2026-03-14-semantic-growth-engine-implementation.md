# Semantic Growth Engine Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the Semantic Growth Engine (Sensor, Interpreter, Modeler, Composer) using deer-flow's Hub-and-Spoke Subagent architecture and a Hybrid Symbolic Diagnostic Engine.

**Architecture:** A central `lead_agent` orchestrated via a new Skill (`semantic-orchestrator`). It delegates to 4 custom subagents configured in `subagents_config.py`. The Modeler subagent calculates risks using a new custom `bayesian_inference` tool wrapping `pgmpy`.

**Tech Stack:** Python 3.12, LangGraph (deer-flow runtime), `pgmpy` (Bayesian inference), Pydantic.

---

### Task 1: Add Dependencies & Create Industry Configs

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/src/config/industry_maps/traditional_manufacturing.json`
- Create: `backend/src/config/industry_maps/high_tech.json`

**Step 1: Update dependencies**
Add `pgmpy` to the `dependencies` list in `backend/pyproject.toml`.

**Step 2: Install dependencies**
Run: `cd backend && uv sync`
Expected: Successfully installs `pgmpy`.

**Step 3: Create Industry Dictionaries**
Create the JSON files containing basic Benchmark Data and strategy-behavior conflict rules (e.g., {"industry": "manufacturing", "avg_margin": "15%", "rules": [...]}).

**Step 4: Commit**
```bash
cd backend
git add pyproject.toml uv.lock src/config/industry_maps/
git commit -m "feat(semantic-engine): add pgmpy dependency and industry map configs"
```

---

### Task 2: Create the Hybrid Symbolic Engine Tool

**Files:**
- Create: `backend/tests/tools/test_bayesian_tool.py`
- Create: `backend/src/tools/builtins/bayesian_inference.py`

**Step 1: Write the failing test**
In `test_bayesian_tool.py`, write a test that passes a mock list of `Symptoms` (e.g., `["CTO_departure", "R&D_drop"]`) and asserts a probability score `> 0.0` for `Management_Gap`.

**Step 2: Run test to verify it fails**
Run: `cd backend && pytest tests/tools/test_bayesian_tool.py`
Expected: FAIL (File not found / import error).

**Step 3: Write minimal implementation**
In `bayesian_inference.py`, implement a `@tool` named `calculate_bayesian_risk`. Define a basic `pgmpy` BayesianModel mapping symptoms to a Root Cause. Expose an empty `update_priors` stub for the RLHF hook.

**Step 4: Run test to verify it passes**
Run: `cd backend && pytest tests/tools/test_bayesian_tool.py`
Expected: PASS.

**Step 5: Register the tool**
Modify `backend/src/tools/tools.py` (or equivalent registry) to include the new `calculate_bayesian_risk` tool.

**Step 6: Commit**
```bash
git add src/tools/builtins/bayesian_inference.py src/tools/tools.py tests/tools/test_bayesian_tool.py
git commit -m "feat(semantic-engine): implement bayesian inference tool with pgmpy"
```

---

### Task 3: Configure the 4 Semantic Subagents

**Files:**
- Modify: `backend/src/config/subagents_config.py`

**Step 1: Write configuration**
Add 4 new `SubagentConfig` entries to the registry:
1. `sensor_agent`: allowed tools `[web_search, read_file]`. Prompt instructs it to read the industry JSONs and calculate time-decay / benchmark deviations.
2. `interpreter_agent`: allowed tools `[read_file]`. Prompt instructs "Strategy-Behaviour Hedging" logic to output Symptoms.
3. `modeler_agent`: allowed tools `[calculate_bayesian_risk, ask_clarification]`. Prompt enforces the RAR Reflection Gate and HITL check for contracts >1M.
4. `composer_agent`: allowed tools `[write_file]`. Prompt enforces 1:1 mentor tone, no sales pitches, diagnostic issue focus.

**Step 2: Verify Configuration Syntax**
Run: `cd backend && make lint`
Expected: Pass (No Python syntax errors in `subagents_config.py`).

**Step 3: Commit**
```bash
git add src/config/subagents_config.py
git commit -m "feat(semantic-engine): register sensor, interpreter, modeler, composer subagents"
```

---

### Task 4: Create the Semantic Orchestrator Skill

**Files:**
- Create: `skills/custom/semantic-orchestrator/SKILL.md`

**Step 1: Write the Orchestrator Skill**
Create the markdown file defining the workflow for the `lead_agent`. It must explicitly instruct the `lead_agent` to use the `task()` tool sequentially:
1. Run `task(description=..., prompt=..., subagent_type="sensor_agent")`
2. Run `task(description=..., prompt=..., subagent_type="interpreter_agent")`
3. Run `task(description=..., prompt=..., subagent_type="modeler_agent")`
4. Run `task(description=..., prompt=..., subagent_type="composer_agent")`
Include instructions to pass the required outputs from one step to the inputs of the next.

**Step 2: Validate the skill structure**
Ensure it follows the `deer-flow` skill schema requirements.

**Step 3: Commit**
```bash
git add skills/custom/semantic-orchestrator/SKILL.md
git commit -m "feat(semantic-engine): add orchestrator skill for subagent pipeline"
```
