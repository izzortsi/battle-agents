"""Cognition package — LLM-driven agent decision-making.

Phase 4: Full generative agent architecture with pre-battle social phase
and combat phase. Memory stream, perception encoding, retrieval, reflection,
planning, dialogue, and action decision for both phases.
"""

from cognition.cognitive_loop import CognitiveLoop, CognitiveState
from cognition.decision import CombatDecision
from cognition.dialogue import DialogueExchange, DialogueSession, run_dialogue_session
from cognition.memory_stream import MemoryNode, MemoryStream, MemoryType
from cognition.planner import Planner
from cognition.pre_battle_decision import decide_pre_battle
from cognition.reflection import reflect

__all__ = [
    "CognitiveLoop",
    "CognitiveState",
    "CombatDecision",
    "DialogueExchange",
    "DialogueSession",
    "MemoryNode",
    "MemoryStream",
    "MemoryType",
    "Planner",
    "decide_pre_battle",
    "reflect",
    "run_dialogue_session",
]
