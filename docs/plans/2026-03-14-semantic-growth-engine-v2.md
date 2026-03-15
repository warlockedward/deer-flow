# Semantic Growth Engine V2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build V2 of the Semantic Growth Engine with advanced causality, multi-source verification, and time-decay weighting.

**Architecture:** Configuration-driven dynamic DAG construction using `pgmpy`. Subagents (Sensor, Interpreter, Modeler) are updated to handle structured signal metadata and schema-defined conflict rules.

**Tech Stack:** Python 3.12, pgmpy, LangGraph, JSON.

---

### Task 1: Update Industry Configuration Schema

**Files:**
- Modify: `backend/src/config/industry_maps/traditional_manufacturing.json`

**Step 1: Update JSON with V2 schema**

```json
{
  "industry": "traditional_manufacturing",
  "signals": {
    "decay_rate_months": 6,
    "multi_source_threshold": 2
  },
  "causal_relationships": [
    {
      "cause": "Management_Gap",
      "effect": "CTO_departure",
      "strength": "strong"
    },
    {
      "cause": "Management_Gap",
      "effect": "RD_drop",
      "strength": "medium"
    }
  ],
  "conflict_rules": [
    {
      "claim": "Innovation Leader",
      "behavior": "Decreasing R&D Investment",
      "severity": "high",
      "trigger_signals": ["RD_drop", "Patent_stagnation"],
      "symptom_output": "Strategic-Behavioral Mismatch: Innovation Stagnation"
    }
  ]
}
```

**Step 2: Commit**

```bash
git add backend/src/config/industry_maps/traditional_manufacturing.json
git commit -m "config: update traditional_manufacturing to V2 schema"
```

---

### Task 2: Implement Dynamic DAG Construction in Bayesian Engine

**Files:**
- Modify: `backend/src/tools/builtins/bayesian_inference.py`
- Test: `backend/tests/tools/test_bayesian_inference_v2.py`

**Step 1: Write failing test for dynamic DAG loading**

```python
import pytest
from src.tools.builtins.bayesian_inference import calculate_bayesian_risk

def test_dynamic_dag_loading():
    # Test with a mock signal list
    signals = [{"name": "CTO_departure", "timestamp": "2025-01-01", "source": "LinkedIn"}]
    # This should fail initially as the tool doesn't handle signal objects or dynamic DAGs
    risk = calculate_bayesian_risk(signals)
    assert isinstance(risk, float)
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/tools/test_bayesian_inference_v2.py`
Expected: FAIL (TypeError or AttributeError)

**Step 3: Implement dynamic DAG construction and strength mapping**

```python
import json
import math
from datetime import datetime
from pgmpy.models import DiscreteBayesianNetwork
from pgmpy.factors.discrete import TabularCPD
from pgmpy.inference import VariableElimination

STRENGTH_MAP = {
    "strong": [[0.9, 0.2], [0.1, 0.8]],
    "medium": [[0.7, 0.3], [0.3, 0.7]],
    "weak": [[0.6, 0.4], [0.4, 0.6]]
}

def load_industry_config(path):
    with open(path, 'r') as f:
        return json.load(f)

def build_network(config):
    model = DiscreteBayesianNetwork()
    # Add edges and CPDs based on config
    # ... (Implementation details for pgmpy)
    return model
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/tools/test_bayesian_inference_v2.py`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/src/tools/builtins/bayesian_inference.py
git commit -m "feat: implement dynamic DAG construction in bayesian engine"
```

---

### Task 3: Implement Multi-Source Verification and Time Decay

**Files:**
- Modify: `backend/src/tools/builtins/bayesian_inference.py`

**Step 1: Add time decay and verification logic to `calculate_bayesian_risk`**

```python
def calculate_bayesian_risk(signals: list[dict]) -> float:
    config = load_industry_config(...)
    decay_rate = config["signals"]["decay_rate_months"]
    threshold = config["signals"]["multi_source_threshold"]
    
    verified_signals = {}
    for s in signals:
        # 1. Time Decay
        age_months = (datetime.now() - datetime.fromisoformat(s["timestamp"])).days / 30
        weight = math.exp(-age_months / decay_rate)
        
        # 2. Multi-source Verification
        # ... (Logic to group by name and count unique sources)
    
    # 3. Run Inference
    # ...
```

**Step 2: Run tests**

Run: `pytest backend/tests/tools/test_bayesian_inference_v2.py`
Expected: PASS

**Step 3: Commit**

```bash
git add backend/src/tools/builtins/bayesian_inference.py
git commit -m "feat: add multi-source verification and time decay to bayesian engine"
```

---

### Task 4: Update Subagent Prompts

**Files:**
- Modify: `backend/src/subagents/builtins/semantic_engine.py`

**Step 1: Update Sensor Agent prompt**

```python
SENSOR_AGENT_CONFIG = SubagentConfig(
    # ...
    system_prompt="""You are a sensor agent. Your job is to:
1. Read industry JSON files.
2. Extract signals with metadata: {"name": "...", "timestamp": "YYYY-MM-DD", "source": "...", "value": "..."}.
3. Apply initial time-decay filtering based on the 'decay_rate_months' in the config.
""",
)
```

**Step 2: Update Interpreter Agent prompt**

```python
INTERPRETER_AGENT_CONFIG = SubagentConfig(
    # ...
    system_prompt="""You are an interpreter agent. Your job is to:
1. Use the 'conflict_rules' from the config.
2. Identify mismatches between claims and behaviors.
3. Assign 'severity' based on the rule definition and evidence strength.
""",
)
```

**Step 3: Update Modeler Agent prompt**

```python
MODELER_AGENT_CONFIG = SubagentConfig(
    # ...
    system_prompt="""You are a modeler agent. Your job is to:
1. Aggregate signals from Sensor and Symptoms from Interpreter.
2. Use 'calculate_bayesian_risk' with full signal metadata.
3. Enforce RAR Reflection Gate.
""",
)
```

**Step 4: Commit**

```bash
git add backend/src/subagents/builtins/semantic_engine.py
git commit -m "feat: update subagent prompts for V2 causality logic"
```
