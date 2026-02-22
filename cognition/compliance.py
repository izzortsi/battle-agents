"""Compliance evaluation — LLM-driven agency override for player commands.

When a player-controlled agent's accumulated tension crosses their
compliance_threshold, this module evaluates whether the agent complies,
refuses, or rebels against the order.

Outcomes:
  comply_reluctant — Executes order, complains verbally, tension -10
  refuse           — Replaces action with WAIT, verbal refusal, tension -20
  rebel            — LLM picks alternate action, tension resets to 0
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from llm.json_utils import extract_json

if TYPE_CHECKING:
    from agent.agent import Agent
    from combat.actions import CombatAction
    from llm.adapter import LLMAdapter
    from world.environment import Environment

log = logging.getLogger(__name__)

COMPLIANCE_SYSTEM_PROMPT = """\
You are the inner voice of {name}, a {combat_class} with alignment {alignment}.

Personality: {personality}
Backstory: {backstory}

You have been ordered by your commander to perform an action. Your accumulated \
grievances have reached a breaking point.

Evaluate whether you comply, refuse, or rebel.

Respond with a JSON object:
{{
  "outcome": "comply_reluctant" | "refuse" | "rebel",
  "dialogue": "<what you say aloud (1-2 sentences, in character)>",
  "reasoning": "<brief internal reasoning>",
  "rebel_action": {{
    "action_type": "attack" | "defend" | "wait" | "move",
    "target_agent": "<agent_id or null>",
    "target_tile": "<x_y or null>",
    "reasoning": "<why this instead>"
  }}
}}

Rules:
- rebel_action is required only if outcome == \"rebel\".
- If action_type == \"attack\", target_agent must be set.
- If action_type == \"move\", target_tile must be set.
"""

COMPLIANCE_USER_PROMPT = """\
SITUATION:
- You are {name} (tension: {tension}/{threshold})
- Order: {action_description}
- Target: {target_name} (your disposition toward them: {disposition})

Recent grievances:
{grievances}

What do you do? Respond with JSON only."""


def build_action_description(action: CombatAction, env: Environment) -> str:
    """Build a human-readable description of the player's order."""
    from combat.actions import ActionType

    if action.action_type == ActionType.ATTACK:
        target = env.agents.get(action.target_agent) if action.target_agent else None
        target_name = target.name if target else action.target_agent or "unknown"
        return f"Attack {target_name}"
    if action.action_type == ActionType.ABILITY:
        target = env.agents.get(action.target_agent) if action.target_agent else None
        target_name = target.name if target else "unknown"
        ability = action.ability_name or "unknown ability"
        return f"Use {ability} on {target_name}"
    if action.action_type == ActionType.MOVE:
        return f"Move to {action.target_tile}"
    if action.action_type == ActionType.DEFEND:
        return "Defend"
    return action.action_type.value


def evaluate_compliance(
    agent: Agent,
    action: CombatAction,
    env: Environment,
    llm: LLMAdapter,
) -> dict:
    """Evaluate whether the agent complies with the player's order.

    Returns a dict with keys:
      outcome: "comply_reluctant" | "refuse" | "rebel"
      dialogue: str
      reasoning: str
      rebel_action: dict | None
    """
    target_id = action.target_agent
    target = env.agents.get(target_id) if target_id else None

    disposition = agent.social.get_disposition(target_id) if target_id else 0.0
    target_name = target.name if target else (target_id or "no target")
    action_desc = build_action_description(action, env)
    grievances = _build_grievance_summary(agent, env)

    system = COMPLIANCE_SYSTEM_PROMPT.format(
        name=agent.name,
        combat_class=agent.identity.combat_class,
        alignment=agent.alignment.label,
        personality=", ".join(agent.identity.personality_traits),
        backstory=(agent.identity.backstory or "")[:200],
    )

    user = COMPLIANCE_USER_PROMPT.format(
        name=agent.name,
        tension=agent.tension,
        threshold=agent.compliance_threshold,
        action_description=action_desc,
        target_name=target_name,
        disposition=f"{disposition:+.2f}",
        grievances=grievances or "- None recorded",
    )

    try:
        raw = llm.complete(
            system=system,
            user=user,
            max_tokens=256,
            temperature=0.7,
            response_format="json",
        )
        data = extract_json(raw)
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict, got {type(data).__name__}")
    except Exception as e:
        log.warning(
            "Compliance eval failed for %s: %s — defaulting to comply_reluctant",
            agent.name,
            e,
        )
        return {
            "outcome": "comply_reluctant",
            "dialogue": f"{agent.name} grits their teeth but follows the order.",
            "reasoning": "LLM evaluation failed",
            "rebel_action": None,
        }

    outcome = data.get("outcome", "comply_reluctant")
    if outcome not in ("comply_reluctant", "refuse", "rebel"):
        outcome = "comply_reluctant"

    rebel_action = data.get("rebel_action") if outcome == "rebel" else None

    return {
        "outcome": outcome,
        "dialogue": data.get("dialogue", "..."),
        "reasoning": data.get("reasoning", ""),
        "rebel_action": rebel_action,
    }


def apply_compliance_result(agent: Agent, result: dict) -> None:
    """Apply tension adjustments based on compliance outcome."""
    outcome = result.get("outcome")
    if outcome == "comply_reluctant":
        agent.tension = max(0, agent.tension - 10)
    elif outcome == "refuse":
        agent.tension = max(0, agent.tension - 20)
    elif outcome == "rebel":
        agent.tension = 0


def _build_grievance_summary(agent: Agent, env: Environment) -> str:
    lines: list[str] = []

    # Relationship-based grievances
    for rel_id, rel in agent.social.all_relationships().items():
        other = env.agents.get(rel_id)
        if not other:
            continue
        if rel.disposition < -0.3:
            lines.append(
                f"- Deep animosity toward {other.name} (disposition: {rel.disposition:+.2f})"
            )
        if not other.is_alive and rel.disposition > 0.15:
            lines.append(
                f"- Ally {other.name} was killed (was disposition {rel.disposition:+.2f})"
            )

    # HP-based grievance
    if agent.attributes.max_hp > 0:
        hp_pct = agent.attributes.hp / agent.attributes.max_hp
        if hp_pct < 0.3:
            lines.append(
                f"- Badly wounded ({agent.attributes.hp}/{agent.attributes.max_hp} HP)"
            )

    return "\n".join(lines[:5])
