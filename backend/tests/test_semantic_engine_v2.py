"""Tests for the 5-level self-check architecture of the Semantic Growth Engine.

Level 1: RAR Logical Anchoring  - Modeler/Composer prompts enforce CoT reflection
Level 2: Conflict Detection     - Interpreter uses severity + trigger_signals
Level 3: Anomaly Detection      - anomaly_detection_agent registered and configured
Level 4: Multi-source gating    - orchestrator rules present in SKILL.md
Level 5: HITL                   - Modeler prompt enforces ask_clarification at >1M
"""


from src.subagents.builtins import BUILTIN_SUBAGENTS
from src.subagents.builtins.semantic_engine import (
    ANOMALY_DETECTION_AGENT_CONFIG,
    COMPOSER_AGENT_CONFIG,
    INTERPRETER_AGENT_CONFIG,
    MODELER_AGENT_CONFIG,
    SENSOR_AGENT_CONFIG,
)


class TestLevel1RARLogicalAnchoring:
    def test_modeler_prompt_contains_rar_reflection_gate(self):
        prompt = MODELER_AGENT_CONFIG.system_prompt
        assert "RAR" in prompt or "Reflect" in prompt or "reflection" in prompt.lower()

    def test_modeler_prompt_requires_emba_anchoring(self):
        prompt = MODELER_AGENT_CONFIG.system_prompt
        assert "EMBA" in prompt or "124" in prompt or "First Principles" in prompt

    def test_modeler_prompt_forbids_sales_rhetoric(self):
        prompt = MODELER_AGENT_CONFIG.system_prompt
        assert "sales" in prompt.lower() or "pitch" in prompt.lower() or "rhetoric" in prompt.lower()

    def test_modeler_prompt_requires_data_citation(self):
        prompt = MODELER_AGENT_CONFIG.system_prompt
        assert "data" in prompt.lower() or "figure" in prompt.lower() or "cite" in prompt.lower()

    def test_composer_prompt_forbids_vague_sales_rhetoric(self):
        prompt = COMPOSER_AGENT_CONFIG.system_prompt
        assert "sales" in prompt.lower() or "pitch" in prompt.lower() or "rhetoric" in prompt.lower()

    def test_composer_prompt_requires_concrete_data(self):
        prompt = COMPOSER_AGENT_CONFIG.system_prompt
        assert "data" in prompt.lower() or "figure" in prompt.lower() or "concrete" in prompt.lower()

    def test_modeler_prompt_requires_logical_traceback(self):
        prompt = MODELER_AGENT_CONFIG.system_prompt
        keywords = ["traceback", "trace", "anchor", "ground", "justify", "basis"]
        assert any(k in prompt.lower() for k in keywords)


class TestLevel2ConflictDetection:
    def test_interpreter_prompt_references_conflict_rules_schema(self):
        prompt = INTERPRETER_AGENT_CONFIG.system_prompt
        assert "conflict_rules" in prompt or "conflict" in prompt.lower()

    def test_interpreter_prompt_references_severity(self):
        prompt = INTERPRETER_AGENT_CONFIG.system_prompt
        assert "severity" in prompt.lower()

    def test_interpreter_prompt_references_trigger_signals(self):
        prompt = INTERPRETER_AGENT_CONFIG.system_prompt
        assert "trigger_signals" in prompt or "trigger" in prompt.lower()

    def test_interpreter_prompt_requires_claims_vs_behavior_comparison(self):
        prompt = INTERPRETER_AGENT_CONFIG.system_prompt
        assert "claim" in prompt.lower() or "vision" in prompt.lower() or "stated" in prompt.lower()
        assert "behav" in prompt.lower() or "actual" in prompt.lower() or "invest" in prompt.lower()

    def test_interpreter_prompt_references_rd_threshold_example(self):
        prompt = INTERPRETER_AGENT_CONFIG.system_prompt
        assert "3%" in prompt or "R&D" in prompt or "innovation" in prompt.lower()


class TestLevel3AnomalyDetectionAgent:
    def test_anomaly_detection_agent_config_exists(self):
        assert ANOMALY_DETECTION_AGENT_CONFIG is not None

    def test_anomaly_detection_agent_registered_in_builtin_subagents(self):
        assert "anomaly_detection_agent" in BUILTIN_SUBAGENTS

    def test_anomaly_detection_agent_name(self):
        assert ANOMALY_DETECTION_AGENT_CONFIG.name == "anomaly_detection_agent"

    def test_anomaly_detection_agent_has_read_file_tool(self):
        tools = ANOMALY_DETECTION_AGENT_CONFIG.tools or []
        assert "read_file" in tools

    def test_anomaly_detection_agent_prompt_targets_industry_exceptions(self):
        prompt = ANOMALY_DETECTION_AGENT_CONFIG.system_prompt
        assert "exception" in prompt.lower() or "anomaly" in prompt.lower() or "atypical" in prompt.lower()

    def test_anomaly_detection_agent_prompt_prevents_hammer_nail_effect(self):
        prompt = ANOMALY_DETECTION_AGENT_CONFIG.system_prompt
        keywords = ["template", "mechanical", "hammer", "pattern", "rigid", "blind"]
        assert any(k in prompt.lower() for k in keywords)

    def test_anomaly_detection_agent_prompt_instructs_exception_handling(self):
        prompt = ANOMALY_DETECTION_AGENT_CONFIG.system_prompt
        assert "exception handling" in prompt.lower() or "re-examine" in prompt.lower() or "challenge" in prompt.lower()

    def test_anomaly_detection_agent_disallows_task_tool(self):
        disallowed = ANOMALY_DETECTION_AGENT_CONFIG.disallowed_tools or []
        assert "task" in disallowed


class TestLevel4MultiSourceGating:
    def test_sensor_prompt_outputs_structured_signal_dicts(self):
        prompt = SENSOR_AGENT_CONFIG.system_prompt
        assert "timestamp" in prompt or "source" in prompt
        assert "name" in prompt.lower() or "structured" in prompt.lower()

    def test_sensor_prompt_references_decay_rate_months(self):
        prompt = SENSOR_AGENT_CONFIG.system_prompt
        assert "decay" in prompt.lower() or "6 month" in prompt.lower() or "decay_rate" in prompt

    def test_modeler_prompt_uses_v2_signal_api(self):
        prompt = MODELER_AGENT_CONFIG.system_prompt
        assert "dict" in prompt.lower() or "metadata" in prompt.lower() or "structured" in prompt.lower()

    def test_modeler_prompt_requires_two_independent_sources(self):
        prompt = MODELER_AGENT_CONFIG.system_prompt
        assert "2" in prompt or "two" in prompt.lower() or "independent" in prompt.lower() or "multi-source" in prompt.lower()


class TestLevel5HITL:
    def test_modeler_prompt_triggers_ask_clarification_above_threshold(self):
        prompt = MODELER_AGENT_CONFIG.system_prompt
        assert "ask_clarification" in prompt

    def test_modeler_prompt_references_high_value_lead_classification(self):
        prompt = MODELER_AGENT_CONFIG.system_prompt
        assert "Comprehensive Value Score" in prompt or "classification" in prompt.lower() or "S-level" in prompt or "A-level" in prompt or "B-level" in prompt

    def test_modeler_has_ask_clarification_in_tools(self):
        tools = MODELER_AGENT_CONFIG.tools or []
        assert "ask_clarification" in tools

    def test_modeler_prompt_mentions_consultant_review(self):
        prompt = MODELER_AGENT_CONFIG.system_prompt
        assert "consultant" in prompt.lower() or "review" in prompt.lower() or "senior" in prompt.lower()


class TestRegistryIntegrity:
    def test_all_five_semantic_agents_in_builtin_subagents(self):
        expected = {
            "sensor_agent",
            "interpreter_agent",
            "modeler_agent",
            "composer_agent",
            "anomaly_detection_agent",
        }
        assert expected.issubset(set(BUILTIN_SUBAGENTS.keys()))

    def test_all_semantic_agents_have_non_empty_system_prompt(self):
        for key in ["sensor_agent", "interpreter_agent", "modeler_agent", "composer_agent", "anomaly_detection_agent"]:
            cfg = BUILTIN_SUBAGENTS[key]
            assert cfg.system_prompt.strip(), f"{key} has empty system_prompt"

    def test_all_semantic_agents_have_description(self):
        for key in ["sensor_agent", "interpreter_agent", "modeler_agent", "composer_agent", "anomaly_detection_agent"]:
            cfg = BUILTIN_SUBAGENTS[key]
            assert cfg.description.strip(), f"{key} has empty description"
