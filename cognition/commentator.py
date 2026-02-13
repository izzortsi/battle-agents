"""Commentator — LLM-powered arena play-by-play narration.

Generates dramatic commentary after each significant combat action.
Maintains a sliding window of recent events for context continuity.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from llm.prompts.commentary import (
    build_action_prompt,
    build_commentary_system,
    build_death_prompt,
    build_victory_prompt,
)

if TYPE_CHECKING:
    from llm.adapter import LLMAdapter

log = logging.getLogger(__name__)


class Commentator:
    """Arena commentator that generates play-by-play narration."""

    def __init__(
        self,
        llm: LLMAdapter,
        lore_text: str = "",
        max_recent: int = 8,
    ) -> None:
        self._llm = llm
        self._system = build_commentary_system(lore_text)
        self._recent_events: list[str] = []
        self._max_recent = max_recent

    def _record(self, description: str) -> None:
        """Add an event to the sliding window."""
        self._recent_events.append(description)
        if len(self._recent_events) > self._max_recent:
            self._recent_events = self._recent_events[-self._max_recent:]

    def _call_llm(self, user_prompt: str) -> str:
        """Call the LLM and return commentary text."""
        try:
            text = self._llm.complete(
                system=self._system,
                user=user_prompt,
                max_tokens=100,
                temperature=0.8,
            )
            return text.strip().strip('"')
        except Exception as e:
            log.warning(f"Commentary generation failed: {e}")
            return ""

    def comment_on_action(self, action_description: str) -> str:
        """Generate commentary for a combat action."""
        self._record(action_description)
        prompt = build_action_prompt(action_description, self._recent_events)
        return self._call_llm(prompt)

    def comment_on_death(self, victim_name: str, killer_name: str) -> str:
        """Generate commentary for a character death."""
        desc = f"{victim_name} has been slain by {killer_name}!"
        self._record(desc)
        prompt = build_death_prompt(victim_name, killer_name, self._recent_events)
        return self._call_llm(prompt)

    def comment_on_victory(
        self,
        winner_name: str,
        winner_class: str,
        rounds: int,
    ) -> str:
        """Generate commentary for the final victory."""
        desc = f"{winner_name} wins the battle!"
        self._record(desc)
        prompt = build_victory_prompt(
            winner_name, winner_class, rounds, self._recent_events
        )
        return self._call_llm(prompt)
