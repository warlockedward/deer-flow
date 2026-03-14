# Semantic Engine Dependencies & Industry Configs Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `pgmpy` dependency and create industry-specific configuration files for the Semantic Growth Engine.

**Architecture:** Update backend dependencies using `uv` and create JSON configuration files in a dedicated directory for agent consumption.

**Tech Stack:** Python, `uv`, JSON.

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

Create the JSON files containing basic Benchmark Data and strategy-behavior conflict rules.

For `traditional_manufacturing.json`:
```json
{
  "industry": "traditional_manufacturing",
  "benchmarks": {
    "avg_gross_margin": 0.15,
    "r_and_d_ratio": 0.03,
    "labor_productivity_ratio": 1.2
  },
  "conflict_rules": [
    {
      "claim": "Innovation Leader",
      "behavior": "Decreasing R&D Investment",
      "symptom_output": "Cost Structure Out of Control"
    }
  ]
}
```

For `high_tech.json`:
```json
{
  "industry": "high_tech",
  "benchmarks": {
    "avg_gross_margin": 0.60,
    "r_and_d_ratio": 0.20,
    "talent_retention_rate": 0.85
  },
  "conflict_rules": [
    {
      "claim": "Talent-Driven Organization",
      "behavior": "High Key-Person Turnover",
      "symptom_output": "Organizational Capability Fracture"
    }
  ]
}
```

**Step 4: Commit**

```bash
cd backend
git add pyproject.toml uv.lock src/config/industry_maps/
git commit -m "feat(semantic-engine): add pgmpy dependency and industry map configs"
```
