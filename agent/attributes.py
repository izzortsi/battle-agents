"""Agent attributes — core stats, derived properties, status effects.

CT-inspired stat system with 5 core stats:
  ATK  – physical damage
  MGK  – magical damage & mana pool
  SPD  – initiative, evasion, movement bonus
  CON  – HP pool, contributes to both defences
  HIT  – accuracy, counter-attack chance

Derived properties (depend on BalanceConfig):
  max_hp, max_mana, phys_def, mag_def, move_range, damage_type
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BalanceConfig:
    """Tunable balance coefficients loaded from game_config.yaml."""

    # HP / Mana derivation
    hp_base: int = 40
    hp_per_con: int = 8
    mana_base: int = 10
    mana_per_mgk: int = 3

    # Movement
    move_base: int = 3
    spd_move_threshold: int = 14
    spd_move_divisor: int = 2

    # CT damage formula
    atk_multiplier: float = 2.0
    def_multiplier: float = 0.667
    damage_variance_low: float = 0.9
    damage_variance_high: float = 1.1

    # Defense derivation
    con_def_weight: float = 1.0
    stat_def_weight: float = 0.5

    # Hit / Evasion
    hit_base_bonus: int = 80
    hit_floor: int = 20
    hit_ceiling: int = 99

    # Crits
    crit_base_chance: float = 6.0
    crit_per_spd: float = 0.5
    crit_multiplier: float = 2.0

    # Counter-attacks
    counter_base_chance: float = 0.0
    counter_per_hit: float = 1.5
    counter_damage_multiplier: float = 0.5

    # Mana regen
    mana_regen_per_round: int = 2

    # Defend action
    defend_bonus_fraction: float = 0.5
    defend_diminishing: float = 0.5


# Module-level default; overwritten by config_loader at startup.
_balance = BalanceConfig()


def set_balance(cfg: BalanceConfig) -> None:
    """Replace the module-level balance config (called once at load time)."""
    global _balance
    _balance = cfg


def get_balance() -> BalanceConfig:
    """Return the current balance config."""
    return _balance


@dataclass
class Attributes:
    """Core stats for an agent.  Mutable — HP/mana change during combat."""

    # -- 5 core stats (1-20 scale) --
    atk: int = 10
    mgk: int = 10
    spd: int = 10
    con: int = 10
    hit: int = 10

    # Class-level property set per character YAML
    attack_range: int = 1  # melee = 1, ranged > 1

    # Runtime mutable state (initialised in __post_init__)
    hp: int = -1  # sentinel; set to max_hp in __post_init__
    mana: int = -1  # sentinel; set to max_mana in __post_init__

    # Status effect tracking
    status_effects: list[dict] = field(default_factory=list)
    # Each: {"type": str, "duration": int, "magnitude": float, "source": str}

    # Abilities — list of ability dicts from character YAML / LLM generation
    abilities: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.hp < 0:
            self.hp = self.max_hp
        if self.mana < 0:
            self.mana = self.max_mana

    # -- Derived properties ------------------------------------------------

    @property
    def max_hp(self) -> int:
        b = _balance
        return b.hp_base + b.hp_per_con * self.con

    @property
    def max_mana(self) -> int:
        b = _balance
        return b.mana_base + b.mana_per_mgk * self.mgk

    @property
    def phys_def(self) -> int:
        """Physical defence: CON + ATK/2."""
        b = _balance
        return int(b.con_def_weight * self.con + b.stat_def_weight * self.atk)

    @property
    def mag_def(self) -> int:
        """Magical defence: CON + MGK/2."""
        b = _balance
        return int(b.con_def_weight * self.con + b.stat_def_weight * self.mgk)

    @property
    def move_range(self) -> int:
        b = _balance
        bonus = max(0, (self.spd - b.spd_move_threshold) // b.spd_move_divisor)
        return b.move_base + bonus

    @property
    def damage_type(self) -> str:
        """'physical' if ATK >= MGK, else 'magical'."""
        return "physical" if self.atk >= self.mgk else "magical"

    @property
    def damage_stat(self) -> int:
        """The higher of ATK and MGK — used in the damage formula."""
        return max(self.atk, self.mgk)

    @property
    def relevant_def(self) -> int:
        """Defence that matches this agent's damage type (for display)."""
        return self.phys_def if self.damage_type == "physical" else self.mag_def

    @property
    def evasion(self) -> int:
        """Evasion score used in hit/evasion contest (alias for SPD)."""
        return self.spd

    # -- Legacy-compatible aliases (used in old attribute refs) --

    @property
    def speed(self) -> int:
        """Alias so turn_manager.roll_initiative still works."""
        return self.spd

    # -- State queries -----------------------------------------------------

    @property
    def is_alive(self) -> bool:
        return self.hp > 0

    # -- Mutators ----------------------------------------------------------

    def take_damage(self, amount: int) -> int:
        """Apply damage, return actual damage dealt."""
        actual = min(amount, self.hp)
        self.hp = max(0, self.hp - amount)
        return actual

    def heal(self, amount: int) -> int:
        """Heal, return actual amount healed."""
        actual = min(amount, self.max_hp - self.hp)
        self.hp = min(self.max_hp, self.hp + amount)
        return actual

    def spend_mana(self, cost: int) -> bool:
        """Spend mana if available.  Returns True if successful."""
        if self.mana < cost:
            return False
        self.mana -= cost
        return True

    def regen_mana(self) -> int:
        """End-of-round mana regen.  Returns amount restored."""
        amount = min(_balance.mana_regen_per_round, self.max_mana - self.mana)
        self.mana += amount
        return amount

    def tick_status_effects(self) -> list[str]:
        """Decrement durations, remove expired effects.  Returns expired effect types."""
        expired: list[str] = []
        remaining: list[dict] = []
        for eff in self.status_effects:
            eff["duration"] -= 1
            if eff["duration"] <= 0:
                expired.append(eff["type"])
            else:
                remaining.append(eff)
        self.status_effects = remaining
        return expired

    def has_status(self, status_type: str) -> bool:
        return any(e["type"] == status_type for e in self.status_effects)

    def get_effective_phys_def(self) -> int:
        """Physical defence including defend status buff."""
        bonus = sum(
            e["magnitude"] for e in self.status_effects if e["type"] == "defend"
        )
        base = self.phys_def
        return int(base + base * bonus)

    def get_effective_mag_def(self) -> int:
        """Magical defence including defend status buff."""
        bonus = sum(
            e["magnitude"] for e in self.status_effects if e["type"] == "defend"
        )
        base = self.mag_def
        return int(base + base * bonus)

    def get_effective_defense(self, damage_type: str = "physical") -> int:
        """Defence for a given damage type, including defend status buff."""
        if damage_type == "magical":
            return self.get_effective_mag_def()
        return self.get_effective_phys_def()

    # -- Ability helpers ---------------------------------------------------

    def tick_cooldowns(self) -> None:
        """Decrement current_cd on all abilities (min 0).  Called at end of round."""
        for ability in self.abilities:
            cd = ability.get("current_cd", 0)
            if cd > 0:
                ability["current_cd"] = cd - 1

    def get_ready_abilities(self) -> list[dict]:
        """Return abilities that are off cooldown and affordable."""
        return [
            a
            for a in self.abilities
            if a.get("current_cd", 0) == 0 and a.get("mana_cost", 0) <= self.mana
        ]

    def get_ability_by_name(self, name: str) -> dict | None:
        """Case-insensitive lookup of an ability by name."""
        low = name.lower().strip()
        for a in self.abilities:
            if a.get("name", "").lower().strip() == low:
                return a
        return None
