"""Tests for character_generator — sprite auto-assignment."""

import pytest

from character_generator import _pick_sprite


# ---- Keyword matching (exact substring in combat_class) ----


class TestPickSpriteKeywords:
    """_pick_sprite selects the correct sprite for known keywords."""

    @pytest.mark.parametrize(
        "combat_class,expected",
        [
            ("archer", "Archer_Female"),
            ("ranger", "Archer_Male"),
            ("berserker", "Berserker"),
            ("cleric", "Cleric"),
            ("healer", "Cleric"),
            ("priest", "Cleric"),
            ("gunslinger", "Gunslinger"),
            ("shadow mage", "Shadow_Mage"),
            ("assassin", "Shadow_Mage"),
            ("cat trickster", "Cat_Shadowmage"),
            ("witch", "Witch"),
            ("wizard", "Wizard_1"),
            ("mage", "Spirit_Mage"),
            ("sorcerer", "Wizard_2"),
            ("necromancer", "Ghost"),
            ("ghost", "Ghost"),
            ("spirit", "Spirit_Mage"),
            ("rogue", "Rogue"),
            ("thief", "Rogue"),
            ("robot", "Robot"),
            ("techno", "Robot"),
            ("mecha", "Mecha"),
            ("machine warrior", "Mecha_Warrior"),
            ("fighter", "Fighter"),
            ("warrior", "Fighter"),
            ("knight", "Fighter"),
            ("paladin", "Fighter"),
        ],
    )
    def test_keyword_match(self, combat_class, expected):
        assert _pick_sprite(combat_class) == expected


# ---- Case insensitivity ----


class TestPickSpriteCaseInsensitive:
    """_pick_sprite is case-insensitive."""

    @pytest.mark.parametrize(
        "combat_class,expected",
        [
            ("ARCHER", "Archer_Female"),
            ("Berserker", "Berserker"),
            ("Shadow Mage", "Shadow_Mage"),
            ("WIZARD", "Wizard_1"),
            ("Gunslinger", "Gunslinger"),
            ("Cat Trickster", "Cat_Shadowmage"),
        ],
    )
    def test_case_insensitive(self, combat_class, expected):
        assert _pick_sprite(combat_class) == expected


# ---- First-match priority ----


class TestPickSpritePriority:
    """Keywords are checked in order; first match wins."""

    def test_shadow_before_mage(self):
        # "shadow mage" contains both "shadow" and "mage"; "shadow" comes first
        assert _pick_sprite("shadow mage") == "Shadow_Mage"

    def test_archer_before_ranger(self):
        # "archer ranger" — "archer" listed before "ranger"
        assert _pick_sprite("archer ranger") == "Archer_Female"

    def test_shadow_before_cat(self):
        # "cat shadow" contains both "shadow" and "cat"; "shadow" is listed
        # earlier in _SPRITE_KEYWORDS so it wins.
        assert _pick_sprite("cat shadow") == "Shadow_Mage"

    def test_cat_keyword_match(self):
        # Pure "cat" (no "shadow" substring) should match the cat entry
        assert _pick_sprite("cat") == "Cat_Shadowmage"


# ---- Fallback ----


class TestPickSpriteFallback:
    """Unknown combat classes fall back to 'Fighter'."""

    @pytest.mark.parametrize(
        "combat_class",
        [
            "bard",
            "dancer",
            "illusionist",
            "unknown class",
            "",
            "xyzzy",
        ],
    )
    def test_fallback_to_fighter(self, combat_class):
        assert _pick_sprite(combat_class) == "Fighter"
