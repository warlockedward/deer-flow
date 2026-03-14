---
name: semantic-orchestrator
description: Orchestrates the Semantic Growth Engine pipeline using specialized subagents (Sensor, Interpreter, Modeler, Composer) to diagnose business issues and generate mentor-style briefings.
---

# Semantic Orchestrator Skill

## Overview

This skill defines the workflow for the `lead_agent` to coordinate the four specialized subagents of the Semantic Growth Engine. You act as the conductor, ensuring each stage of the business diagnosis is completed sequentially and that context is preserved across the pipeline.

## Core Workflow

You MUST execute the following 4 stages sequentially. Wait for each `task()` to complete and pass its output into the prompt of the next stage.

### Stage 1: Signal Acquisition (Sensor)
- **Goal**: Gather raw industry data and scan for signals.
- **Action**: 
  ```python
  task(subagent_type="sensor_agent", prompt="Read industry configs, scan public data, and output raw signals filtered by time-decay and benchmark deviation.", description="Acquire raw signals")
  ```

### Stage 2: Behavioral Interpretation (Interpreter)
- **Goal**: Identify contradictions and behavioral symptoms.
- **Action**: 
  ```python
  task(subagent_type="interpreter_agent", prompt="Pass sensor data here: [SENSOR_OUTPUT]. Apply 'Strategy-Behaviour Hedging' logic to identify contradictions and output behavioral 'Symptoms'.", description="Interpret behavioral symptoms")
  ```

### Stage 3: Risk Modeling (Modeler)
- **Goal**: Calculate Bayesian risk and enforce reflection gates.
- **Action**: 
  ```python
  task(subagent_type="modeler_agent", prompt="Pass interpreter symptoms here: [INTERPRETER_OUTPUT]. Calculate Bayesian risk and enforce RAR Reflection Gate (data backing, no sales pitches, EMBA anchoring).", description="Model business risk")
  ```

### Stage 4: Mentor Briefing (Composer)
- **Goal**: Generate the final 1:1 mentor-style diagnostic brief.
- **Action**: 
  ```python
  task(subagent_type="composer_agent", prompt="Pass modeler conclusion here: [MODELER_OUTPUT]. Draft final mentor-style brief focusing on diagnosing business issues (value-first delivery).", description="Compose mentor brief")
  ```

## Operational Rules

1. **Sequential Only**: Never run these tasks in parallel.
2. **Context Passing**: Explicitly include the previous agent's findings in the next agent's prompt.
3. **Wait for Completion**: The `task()` tool will return the result once the subagent finishes. Do not proceed until you have the result.