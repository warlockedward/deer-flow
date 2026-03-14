"""Built-in subagent configurations."""

from .bash_agent import BASH_AGENT_CONFIG
from .general_purpose import GENERAL_PURPOSE_CONFIG
from .semantic_engine import (
    COMPOSER_AGENT_CONFIG,
    INTERPRETER_AGENT_CONFIG,
    MODELER_AGENT_CONFIG,
    SENSOR_AGENT_CONFIG,
)

__all__ = [
    "GENERAL_PURPOSE_CONFIG",
    "BASH_AGENT_CONFIG",
    "SENSOR_AGENT_CONFIG",
    "INTERPRETER_AGENT_CONFIG",
    "MODELER_AGENT_CONFIG",
    "COMPOSER_AGENT_CONFIG",
]

# Registry of built-in subagents
BUILTIN_SUBAGENTS = {
    "general-purpose": GENERAL_PURPOSE_CONFIG,
    "bash": BASH_AGENT_CONFIG,
    "sensor_agent": SENSOR_AGENT_CONFIG,
    "interpreter_agent": INTERPRETER_AGENT_CONFIG,
    "modeler_agent": MODELER_AGENT_CONFIG,
    "composer_agent": COMPOSER_AGENT_CONFIG,
}
