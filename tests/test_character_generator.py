"""Tests for character_generator — sprite assignment + data-driven registries."""

import pytest
import yaml

from character_generator import (
    _pick_sprite,
    _save_class,
    _save_abilities,
    load_class_registry,
    load_ability_registry,
)


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


# ====================================================================
# Registry tests
# ====================================================================


class TestClassRegistry:
    """load_class_registry / _save_class round-trip."""

    def test_load_returns_dict(self):
        """Seed file exists and loads as a dict."""
        reg = load_class_registry()
        assert isinstance(reg, dict)
        assert len(reg) >= 1

    def test_load_missing_file(self, tmp_path, monkeypatch):
        import character_generator as cg

        monkeypatch.setattr(cg, "_CLASSES_PATH", tmp_path / "nope.yaml")
        assert load_class_registry() == {}

    def test_save_new_class(self, tmp_path, monkeypatch):
        import character_generator as cg

        path = tmp_path / "classes.yaml"
        monkeypatch.setattr(cg, "_CLASSES_PATH", path)
        _save_class("Flame Knight", "Fighter")
        reg = load_class_registry()
        assert "flame knight" in reg
        assert reg["flame knight"]["sprite"] == "Fighter"

    def test_save_duplicate_class_no_overwrite(self, tmp_path, monkeypatch):
        import character_generator as cg

        path = tmp_path / "classes.yaml"
        monkeypatch.setattr(cg, "_CLASSES_PATH", path)
        _save_class("Flame Knight", "Fighter")
        _save_class("Flame Knight", "Berserker")  # same key, different sprite
        reg = load_class_registry()
        assert reg["flame knight"]["sprite"] == "Fighter"  # first write wins

    def test_save_preserves_existing(self, tmp_path, monkeypatch):
        import character_generator as cg

        path = tmp_path / "classes.yaml"
        monkeypatch.setattr(cg, "_CLASSES_PATH", path)
        _save_class("warrior", "Fighter")
        _save_class("ice mage", "Wizard_2")
        reg = load_class_registry()
        assert "warrior" in reg
        assert "ice mage" in reg


class TestAbilityRegistry:
    """load_ability_registry / _save_abilities round-trip."""

    def test_load_returns_list(self):
        """Seed file exists and loads as a list."""
        reg = load_ability_registry()
        assert isinstance(reg, list)
        assert len(reg) >= 1

    def test_load_missing_file(self, tmp_path, monkeypatch):
        import character_generator as cg

        monkeypatch.setattr(cg, "_ABILITIES_PATH", tmp_path / "nope.yaml")
        assert load_ability_registry() == []

    def test_save_new_abilities(self, tmp_path, monkeypatch):
        import character_generator as cg

        path = tmp_path / "abilities.yaml"
        monkeypatch.setattr(cg, "_ABILITIES_PATH", path)
        _save_abilities(
            [
                {"name": "Fireball", "damage": 20, "range": 3, "mana_cost": 8},
                {"name": "Ice Shard", "damage": 12, "range": 4, "mana_cost": 5},
            ]
        )
        reg = load_ability_registry()
        names = [a["name"] for a in reg]
        assert "Fireball" in names
        assert "Ice Shard" in names

    def test_save_deduplicates_by_name(self, tmp_path, monkeypatch):
        import character_generator as cg

        path = tmp_path / "abilities.yaml"
        monkeypatch.setattr(cg, "_ABILITIES_PATH", path)
        _save_abilities([{"name": "Fireball", "damage": 20}])
        _save_abilities([{"name": "Fireball", "damage": 99}])  # duplicate
        reg = load_ability_registry()
        fireballs = [a for a in reg if a["name"] == "Fireball"]
        assert len(fireballs) == 1
        assert fireballs[0]["damage"] == 20  # first write wins

    def test_save_strips_current_cd(self, tmp_path, monkeypatch):
        import character_generator as cg

        path = tmp_path / "abilities.yaml"
        monkeypatch.setattr(cg, "_ABILITIES_PATH", path)
        _save_abilities([{"name": "Slash", "damage": 10, "current_cd": 3}])
        reg = load_ability_registry()
        assert "current_cd" not in reg[0]

    def test_save_skips_empty(self, tmp_path, monkeypatch):
        import character_generator as cg

        path = tmp_path / "abilities.yaml"
        monkeypatch.setattr(cg, "_ABILITIES_PATH", path)
        _save_abilities([])
        assert not path.exists()  # nothing to write


class TestBuildLayer1UserSpriteHint:
    """build_layer1_user includes sprite archetype hint when provided."""

    def test_no_hint(self):
        from llm.prompts.character_gen import build_layer1_user

        text = build_layer1_user("Test", "A test character")
        assert "Visual archetype" not in text

    def test_with_hint(self):
        from llm.prompts.character_gen import build_layer1_user

        text = build_layer1_user("Test", "A test char", sprite_hint="Cat_Shadowmage")
        assert "Visual archetype: Cat Shadowmage" in text
        assert "combat class that fits this look" in text

    def test_hint_none_same_as_no_hint(self):
        from llm.prompts.character_gen import build_layer1_user

        text = build_layer1_user("Test", "A test char", sprite_hint=None)
        assert "Visual archetype" not in text
