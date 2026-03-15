# Design Document: Semantic Growth Engine V2

**Date**: 2026-03-14
**Status**: Approved
**Topic**: Advanced Causality & Dynamic DAG Mapping

## 1. Overview
V2 of the Semantic Growth Engine introduces advanced causality logic to improve the accuracy and transparency of business diagnoses. Key features include multi-source verification, time-decay weighting for signals, and dynamic Directed Acyclic Graph (DAG) construction from industry-specific configurations.

## 2. Architecture & Data Flow
The engine operates as a multi-agent system orchestrated via LangGraph:
1.  **Sensor Agent**: Scans data and extracts signals with metadata (source, timestamp).
2.  **Interpreter Agent**: Detects "Strategy-Behaviour Hedging" (conflicts) using schema-defined rules.
3.  **Modeler Agent**: Constructs a dynamic Bayesian network and calculates risk scores.

## 3. Component Design

### 3.1 Schema Expansion (`traditional_manufacturing.json`)
The configuration schema is expanded to include:
- `signals`: Global parameters for `decay_rate_months` and `multi_source_threshold`.
- `causal_relationships`: A list of edges (`cause`, `effect`) with qualitative `strength`.
- `conflict_rules`: Rules for the Interpreter including `severity` and `trigger_signals`.

### 3.2 Bayesian Engine (`bayesian_inference.py`)
- **Dynamic Construction**: Uses `pgmpy` to build networks at runtime based on the JSON config.
- **Strength Mapping**: Maps "strong", "medium", "weak" to predefined Conditional Probability Distributions (CPDs).
- **Time Decay**: Applies exponential decay $w = e^{-\lambda t}$ to signal confidence.
- **Verification**: Filters signals that do not meet the `multi_source_threshold`.

### 3.3 Subagent Prompts (`semantic_engine.py`)
- **Sensor**: Updated to output structured signal objects with metadata.
- **Interpreter**: Updated to use the new `conflict_rules` and assign `severity`.
- **Modeler**: Updated to pass full signal metadata to the Bayesian tool.

## 4. Implementation Plan Summary
The implementation will follow a three-phase approach:
1.  **Phase 1**: Update industry configurations to the V2 schema.
2.  **Phase 2**: Refactor the Bayesian tool for dynamic execution and metadata handling.
3.  **Phase 3**: Update subagent prompts to utilize the new data structures.
