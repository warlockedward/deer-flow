# Design Doc: Semantic Engine Dependencies & Industry Configs

**Date:** 2026-03-14
**Topic:** Add Dependencies & Create Industry Configs

## Overview
This design covers the initial setup for the Semantic Growth Engine, including adding the core Bayesian inference library (`pgmpy`) and creating industry-specific configuration files for benchmark data and conflict rules.

## Architecture
- **Dependency Management:** `uv` is used for backend dependency management.
- **Configuration:** JSON files stored in `backend/src/config/industry_maps/` will be used by Sensor and Interpreter agents.

## Components
### 1. Backend Dependencies
- **Library:** `pgmpy`
- **Purpose:** Core Bayesian inference for the diagnostic engine.
- **Action:** Update `backend/pyproject.toml` and run `uv sync`.

### 2. Industry Maps
- **Location:** `backend/src/config/industry_maps/`
- **Files:**
    - `traditional_manufacturing.json`
    - `high_tech.json`
- **Schema:**
    - `industry`: String identifier.
    - `benchmarks`: Object containing key performance indicators.
    - `conflict_rules`: List of objects defining strategy-behavior conflicts.

## Data Flow
1. Agents (Sensor/Interpreter) read JSON configs from the industry maps directory.
2. Configs provide benchmarks for comparison and rules for detecting hedging.
3. `pgmpy` is used to perform inference based on detected symptoms and behaviors.

## Testing
- Verify `uv sync` completes without errors.
- Verify JSON files are valid and correctly placed.

## Implementation Plan
1. Modify `backend/pyproject.toml` to add `pgmpy`.
2. Run `uv sync` in `backend/`.
3. Create `backend/src/config/industry_maps/` directory.
4. Create `traditional_manufacturing.json` and `high_tech.json`.
5. Commit changes.
