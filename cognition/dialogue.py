"""Dialogue — synchronous bounded dialogue sessions between agents.

When an agent emits CHAT(target, message), a DialogueSession opens.
The exchange is bounded at L_max rounds (default: 2 in both phases,
yielding max 4 messages / 2 per character). Each response is generated
by a single LLM call.

After the session closes:
  - Each participant gets a summary MemoryNode (from their own perspective)
  - Nearby agents get an "overheard" observation
  - Disposition shifts are applied to social models
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from cognition.memory_stream import MemoryStream, MemoryType
from cognition.retrieval import retrieve
from llm.json_utils import extract_json
from llm.prompts.dialogue import (
    build_dialogue_initiate_prompt,
    build_dialogue_response_prompt,
    build_dialogue_system_prompt,
    build_summary_prompts,
    format_exchange_history,
)
from world.battle_grid import BattleGrid

if TYPE_CHECKING:
    from agent.agent import Agent
    from llm.adapter import LLMAdapter
    from world.environment import Environment

log = logging.getLogger(__name__)


@dataclass
class DialogueExchange:
    """One message in a dialogue session."""

    speaker: str  # agent_id
    speaker_name: str
    message: str
    disposition_shift: float
    round_number: int


@dataclass
class DialogueSession:
    """A bounded dialogue between two agents."""

    initiator: str  # agent_id
    responder: str  # agent_id
    turn_started: int
    max_rounds: int
    exchanges: list[DialogueExchange] = field(default_factory=list)
    status: Literal[
        "active", "ended_by_initiator", "ended_by_responder", "max_rounds"
    ] = "active"

    @property
    def exchange_count(self) -> int:
        """Number of exchange rounds completed (2 messages = 1 round)."""
        return (len(self.exchanges) + 1) // 2

    @property
    def is_active(self) -> bool:
        return self.status == "active"


def run_dialogue_session(
    initiator: Agent,
    responder: Agent,
    initial_message: str,
    env: Environment,
    llm: LLMAdapter,
    initiator_memory: MemoryStream,
    responder_memory: MemoryStream,
    round_number: int,
    max_rounds: int = 2,
) -> DialogueSession:
    """Run a complete bounded dialogue session between two agents.

    The initiator's first message is provided. The responder and initiator
    then alternate generating responses until max_rounds is reached or
    either party signals end.

    Returns the completed DialogueSession.
    """
    current_turn = env.turn_manager.global_turn

    session = DialogueSession(
        initiator=initiator.agent_id,
        responder=responder.agent_id,
        turn_started=current_turn,
        max_rounds=max_rounds,
    )

    # Generate the initiator's opening message via LLM (refine the raw message idea)
    init_msg = _generate_initiator_message(
        initiator,
        responder,
        initial_message,
        env,
        llm,
        initiator_memory,
        round_number,
        current_turn,
    )

    session.exchanges.append(
        DialogueExchange(
            speaker=initiator.agent_id,
            speaker_name=initiator.name,
            message=init_msg["message"],
            disposition_shift=init_msg["disposition_shift"],
            round_number=1,
        )
    )

    # Apply disposition shift for initiator
    initiator.social.update_disposition(
        responder.agent_id,
        init_msg["disposition_shift"],
        f'dialogue (said: "{init_msg["message"][:40]}...")',
        current_turn,
        responder.name,
    )

    log.info(f'    [{initiator.name}] says: "{init_msg["message"]}"')

    # Exchange loop
    for rnd in range(1, max_rounds + 1):
        if not session.is_active:
            break

        # Responder's turn
        resp = _generate_response(
            responder,
            initiator,
            session,
            env,
            llm,
            responder_memory,
            round_number,
            current_turn,
        )
        session.exchanges.append(
            DialogueExchange(
                speaker=responder.agent_id,
                speaker_name=responder.name,
                message=resp["message"],
                disposition_shift=resp["disposition_shift"],
                round_number=rnd,
            )
        )

        # Apply disposition shift for responder
        responder.social.update_disposition(
            initiator.agent_id,
            resp["disposition_shift"],
            f'dialogue (said: "{resp["message"][:40]}...")',
            current_turn,
            initiator.name,
        )

        log.info(f'    [{responder.name}] replies: "{resp["message"]}"')

        if not resp["continue"]:
            session.status = "ended_by_responder"
            break

        # Check if we've hit max rounds
        if rnd >= max_rounds:
            session.status = "max_rounds"
            break

        # Initiator's turn (follow-up)
        follow = _generate_response(
            initiator,
            responder,
            session,
            env,
            llm,
            initiator_memory,
            round_number,
            current_turn,
        )
        session.exchanges.append(
            DialogueExchange(
                speaker=initiator.agent_id,
                speaker_name=initiator.name,
                message=follow["message"],
                disposition_shift=follow["disposition_shift"],
                round_number=rnd + 1,
            )
        )

        # Apply disposition shift for initiator
        initiator.social.update_disposition(
            responder.agent_id,
            follow["disposition_shift"],
            f'dialogue (said: "{follow["message"][:40]}...")',
            current_turn,
            responder.name,
        )

        log.info(f'    [{initiator.name}] says: "{follow["message"]}"')

        if not follow["continue"]:
            session.status = "ended_by_initiator"
            break

    if session.status == "active":
        session.status = "max_rounds"

    # Post-dialogue: emit memory summaries for both participants
    _emit_dialogue_memories(
        session,
        initiator,
        responder,
        env,
        llm,
        initiator_memory,
        responder_memory,
        current_turn,
    )

    return session


def _generate_initiator_message(
    initiator: Agent,
    responder: Agent,
    initial_idea: str,
    env: Environment,
    llm: LLMAdapter,
    memory: MemoryStream,
    round_number: int,
    current_turn: int,
) -> dict:
    """Generate the initiator's opening message."""
    pos = env.world_state.get_position(initiator.agent_id)
    mx, my = BattleGrid.parse_tile(pos) if pos else (0, 0)

    # Get relationship info
    rel = initiator.social.get_relationship(responder.agent_id)
    disposition = rel.disposition if rel else 0.0
    trust = rel.trust if rel else 0.5
    notes = rel.notes if rel else []

    # Retrieve memories about the responder
    query = f"{responder.name} {responder.identity.combat_class}"
    memories = retrieve(memory, query, current_turn, top_k=5)

    system = build_dialogue_system_prompt(initiator)
    user = build_dialogue_initiate_prompt(
        agent=initiator,
        other_name=responder.name,
        round_number=round_number,
        my_x=mx,
        my_y=my,
        disposition=disposition,
        trust=trust,
        relationship_notes=notes,
        memories=memories,
        initial_idea=initial_idea,
    )

    return _call_dialogue_llm(llm, system, user, initiator.name)


def _generate_response(
    speaker: Agent,
    other: Agent,
    session: DialogueSession,
    env: Environment,
    llm: LLMAdapter,
    memory: MemoryStream,
    round_number: int,
    current_turn: int,
) -> dict:
    """Generate a dialogue response from the speaker."""
    pos = env.world_state.get_position(speaker.agent_id)
    mx, my = BattleGrid.parse_tile(pos) if pos else (0, 0)

    # Get relationship info
    rel = speaker.social.get_relationship(other.agent_id)
    disposition = rel.disposition if rel else 0.0
    trust = rel.trust if rel else 0.5
    notes = rel.notes if rel else []

    # Retrieve memories about the other agent
    query = f"{other.name} {other.identity.combat_class}"
    memories = retrieve(memory, query, current_turn, top_k=5)

    # Build conversation history
    history_pairs = [(ex.speaker_name, ex.message) for ex in session.exchanges]
    conversation_history = format_exchange_history(history_pairs)

    # Last message is the most recent exchange from the other party
    last_msg = ""
    for ex in reversed(session.exchanges):
        if ex.speaker != speaker.agent_id:
            last_msg = ex.message
            break
    if not last_msg and session.exchanges:
        last_msg = session.exchanges[-1].message

    system = build_dialogue_system_prompt(speaker)
    user = build_dialogue_response_prompt(
        agent=speaker,
        other_name=other.name,
        round_number=round_number,
        my_x=mx,
        my_y=my,
        disposition=disposition,
        trust=trust,
        relationship_notes=notes,
        memories=memories,
        conversation_history=conversation_history,
        last_message=last_msg,
    )

    return _call_dialogue_llm(llm, system, user, speaker.name)


def _call_dialogue_llm(
    llm: LLMAdapter,
    system: str,
    user: str,
    speaker_name: str,
) -> dict:
    """Call the LLM for a dialogue response and parse the result.

    Returns dict with keys: message, continue, disposition_shift.
    Falls back to defaults on error.
    """
    try:
        raw = llm.complete(
            system=system,
            user=user,
            max_tokens=256,
            temperature=0.8,
            response_format="json",
        )
        parsed = extract_json(raw)
        if not isinstance(parsed, dict):
            raise ValueError(f"Expected dict, got {type(parsed).__name__}")

        msg = str(parsed.get("message", "..."))
        cont = bool(parsed.get("continue", False))
        shift = float(parsed.get("disposition_shift", 0.0))
        # Clamp shift
        shift = max(-0.3, min(0.3, shift))

        return {"message": msg, "continue": cont, "disposition_shift": shift}

    except Exception as e:
        log.warning(f"{speaker_name}: dialogue LLM error: {e}")
        return {
            "message": "...",
            "continue": False,
            "disposition_shift": 0.0,
        }


def _emit_dialogue_memories(
    session: DialogueSession,
    initiator: Agent,
    responder: Agent,
    env: Environment,
    llm: LLMAdapter,
    initiator_memory: MemoryStream,
    responder_memory: MemoryStream,
    current_turn: int,
    use_llm_summary: bool = True,
) -> None:
    """After dialogue closes, create summary memories for each participant.

    If use_llm_summary is False (or the dialogue is very short),
    uses a template-based summary instead of an LLM call to save tokens.
    """
    # Build exchange text for summary
    exchange_lines = []
    for ex in session.exchanges:
        exchange_lines.append(f'{ex.speaker_name}: "{ex.message}"')
    exchange_text = "\n".join(exchange_lines)

    # For short dialogues (<=2 messages), use template summaries
    if len(session.exchanges) <= 2 or not use_llm_summary:
        init_summary = _template_summary(initiator, responder, session)
        resp_summary = _template_summary(responder, initiator, session)
    else:
        # Summarize for initiator
        init_summary = _generate_summary(initiator, responder.name, exchange_text, llm)
        # Summarize for responder
        resp_summary = _generate_summary(responder, initiator.name, exchange_text, llm)

    initiator_memory.add(
        turn=current_turn,
        memory_type=MemoryType.OBSERVATION,
        description=init_summary,
        poignancy=6,  # dialogue is fairly important
        depth=0,
        subject=initiator.name,
        predicate="talked_with",
        object_=responder.name,
    )

    responder_memory.add(
        turn=current_turn,
        memory_type=MemoryType.OBSERVATION,
        description=resp_summary,
        poignancy=6,
        depth=0,
        subject=responder.name,
        predicate="talked_with",
        object_=initiator.name,
    )

    log.info(f"    [Dialogue summary for {initiator.name}]: {init_summary}")
    log.info(f"    [Dialogue summary for {responder.name}]: {resp_summary}")

    # Emit "overheard" observations for nearby agents
    init_pos = env.world_state.get_position(initiator.agent_id)
    if init_pos:
        for other in env.alive_agents():
            if other.agent_id in (initiator.agent_id, responder.agent_id):
                continue
            other_pos = env.world_state.get_position(other.agent_id)
            if other_pos:
                dist = BattleGrid.tile_distance(init_pos, other_pos)
                if dist <= env.perception_engine.perception_radius:
                    # This agent overheard the conversation (but not content)
                    overheard = (
                        f"{initiator.name} and {responder.name} were seen "
                        f"talking intensely nearby."
                    )
                    log.debug(f"  {other.name} overheard dialogue")


def _template_summary(
    agent: Agent,
    other: Agent,
    session: DialogueSession,
) -> str:
    """Generate a fast template-based summary (no LLM call).

    Extracts the key content from the exchange without an LLM call.
    Used for short dialogues to reduce API overhead.
    """
    # Find what the agent said and what the other said
    my_msgs = [ex.message for ex in session.exchanges if ex.speaker == agent.agent_id]
    their_msgs = [
        ex.message for ex in session.exchanges if ex.speaker == other.agent_id
    ]

    my_part = my_msgs[0][:60] if my_msgs else "nothing"
    their_part = their_msgs[0][:60] if their_msgs else "nothing"

    return (
        f"{agent.name} exchanged words with {other.name} during combat. "
        f'{agent.name} said: "{my_part}" — '
        f'{other.name} replied: "{their_part}"'
    )


def _generate_summary(
    agent: Agent,
    other_name: str,
    exchange_text: str,
    llm: LLMAdapter,
) -> str:
    """Generate a dialogue summary from the agent's perspective."""
    try:
        system, user = build_summary_prompts(agent, other_name, exchange_text)
        raw = llm.complete(
            system=system,
            user=user,
            max_tokens=128,
            temperature=0.5,
            response_format="json",
        )
        parsed = extract_json(raw)
        if isinstance(parsed, dict) and "summary" in parsed:
            return str(parsed["summary"])
    except Exception as e:
        log.warning(f"{agent.name}: summary generation failed: {e}")

    # Fallback template
    return f"{agent.name} had a conversation with {other_name} during combat."
