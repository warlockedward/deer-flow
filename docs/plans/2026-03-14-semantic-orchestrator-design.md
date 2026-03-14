# Design Doc: Semantic Orchestrator Skill

**Date**: 2026-03-14
**Topic**: Create the Semantic Orchestrator Skill for the Semantic Growth Engine.

## Overview
The Semantic Orchestrator Skill defines the workflow for the `lead_agent` to coordinate four specialized subagents (`sensor_agent`, `interpreter_agent`, `modeler_agent`, `composer_agent`) in a sequential pipeline. This skill acts as the conductor for the "Semantic Growth Engine".

## Architecture
The system follows a Hub-and-Spoke model where the `lead_agent` (Hub) uses the `task()` tool to delegate specific phases of business diagnosis to subagents (Spokes).

### Pipeline Stages
1. **Sensor**: Signal acquisition from industry configs and public data.
2. **Interpreter**: Behavioral contradiction analysis (Strategy-Behaviour Hedging).
3. **Modeler**: Bayesian risk calculation and reflection gate enforcement.
4. **Composer**: Final mentor-style briefing generation.

## Implementation Details
- **File Path**: `skills/custom/semantic-orchestrator/SKILL.md`
- **Tool Usage**: `task(subagent_type=..., prompt=..., description=...)`
- **Execution Mode**: Sequential (wait for completion, pass output to next).

## Data Flow
- `Sensor Output` -> `Interpreter Input`
- `Interpreter Output` -> `Modeler Input`
- `Modeler Output` -> `Composer Input`

## Verification Plan
- Verify `SKILL.md` exists in the correct directory.
- Verify the content explicitly instructs sequential use of the `task()` tool.
- Verify the subagent types match the registered names in the backend.
