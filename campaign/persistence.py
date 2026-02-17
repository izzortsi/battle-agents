"""Campaign persistence — SQLite backend.

Single-file database at ``data/campaigns.db`` (configurable).
Handles schema creation, save/load for all campaign state.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from campaign.models import (
    BattleRecord,
    CampaignMeta,
    RosterEntry,
    SerializedMemory,
    SerializedRelationship,
)

log = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "campaigns.db"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS campaigns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    created_at      TEXT    NOT NULL,
    battle_count    INTEGER NOT NULL DEFAULT 0,
    lore_json       TEXT    DEFAULT NULL              -- JSON: persisted LoreContext
);

CREATE TABLE IF NOT EXISTS roster (
    campaign_id     INTEGER NOT NULL,
    agent_id        TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    combat_class    TEXT    NOT NULL DEFAULT 'warrior',
    sprite          TEXT    NOT NULL DEFAULT '',
    backstory       TEXT    NOT NULL DEFAULT '',
    personality     TEXT    NOT NULL DEFAULT '[]',   -- JSON list
    alive           INTEGER NOT NULL DEFAULT 1,
    xp              INTEGER NOT NULL DEFAULT 0,
    level           INTEGER NOT NULL DEFAULT 1,
    atk             INTEGER NOT NULL DEFAULT 10,
    mgk             INTEGER NOT NULL DEFAULT 10,
    spd             INTEGER NOT NULL DEFAULT 10,
    con             INTEGER NOT NULL DEFAULT 10,
    hit             INTEGER NOT NULL DEFAULT 10,
    attack_range    INTEGER NOT NULL DEFAULT 1,
    abilities       TEXT    NOT NULL DEFAULT '[]',   -- JSON list
    morality        REAL    NOT NULL DEFAULT 0.0,    -- -1.0 evil … +1.0 good
    order_value     REAL    NOT NULL DEFAULT 0.0,    -- -1.0 chaotic … +1.0 lawful
    PRIMARY KEY (campaign_id, agent_id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

CREATE TABLE IF NOT EXISTS battles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id     INTEGER NOT NULL,
    battle_num      INTEGER NOT NULL,
    winner_ids      TEXT    NOT NULL DEFAULT '[]',   -- JSON list
    death_ids       TEXT    NOT NULL DEFAULT '[]',   -- JSON list
    rounds          INTEGER NOT NULL DEFAULT 0,
    xp_awards       TEXT    NOT NULL DEFAULT '{}',   -- JSON dict
    timestamp       TEXT    NOT NULL,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

CREATE TABLE IF NOT EXISTS memories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id     INTEGER NOT NULL,
    agent_id        TEXT    NOT NULL,
    description     TEXT    NOT NULL,
    poignancy       INTEGER NOT NULL DEFAULT 5,
    memory_type     TEXT    NOT NULL DEFAULT 'observation',
    turn_created    INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

CREATE TABLE IF NOT EXISTS relationships (
    campaign_id         INTEGER NOT NULL,
    owner_id            TEXT    NOT NULL,
    target_id           TEXT    NOT NULL,
    target_name         TEXT    NOT NULL DEFAULT '',
    disposition         REAL    NOT NULL DEFAULT 0.0,
    trust               REAL    NOT NULL DEFAULT 0.5,
    betrayal_count      INTEGER NOT NULL DEFAULT 0,
    alliance_declared   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (campaign_id, owner_id, target_id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);
"""


# ---------------------------------------------------------------------------
# Database handle
# ---------------------------------------------------------------------------


class CampaignDB:
    """SQLite-backed campaign persistence."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        # Migrate existing databases
        self._migrate_alignment_columns()
        self._migrate_lore_column()
        self._migrate_limit_break_column()
        self._conn.commit()

    def _migrate_alignment_columns(self) -> None:
        """Add morality/order_value columns to roster if they don't exist."""
        cols = {
            row[1] for row in self._conn.execute("PRAGMA table_info(roster)").fetchall()
        }
        if "morality" not in cols:
            self._conn.execute(
                "ALTER TABLE roster ADD COLUMN morality REAL NOT NULL DEFAULT 0.0"
            )
        if "order_value" not in cols:
            self._conn.execute(
                "ALTER TABLE roster ADD COLUMN order_value REAL NOT NULL DEFAULT 0.0"
            )

    def _migrate_lore_column(self) -> None:
        """Add lore_json column to campaigns if it doesn't exist."""
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(campaigns)").fetchall()
        }
        if "lore_json" not in cols:
            self._conn.execute(
                "ALTER TABLE campaigns ADD COLUMN lore_json TEXT DEFAULT NULL"
            )

    def _migrate_limit_break_column(self) -> None:
        """Add limit_break column to roster if it doesn't exist."""
        cols = {
            row[1] for row in self._conn.execute("PRAGMA table_info(roster)").fetchall()
        }
        if "limit_break" not in cols:
            self._conn.execute(
                "ALTER TABLE roster ADD COLUMN limit_break TEXT DEFAULT NULL"
            )

    def close(self) -> None:
        self._conn.close()

    # -- Campaign CRUD -------------------------------------------------------

    def create_campaign(self, name: str) -> CampaignMeta:
        """Create a new campaign and return its metadata."""
        meta = CampaignMeta(name=name)
        cur = self._conn.execute(
            "INSERT INTO campaigns (name, created_at, battle_count) VALUES (?, ?, ?)",
            (meta.name, meta.created_at, 0),
        )
        meta.campaign_id = cur.lastrowid  # type: ignore[assignment]
        self._conn.commit()
        log.info("Created campaign '%s' (id=%d)", name, meta.campaign_id)
        return meta

    def get_campaign(self, campaign_id: int) -> CampaignMeta | None:
        row = self._conn.execute(
            "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if not row:
            return None
        return CampaignMeta(
            campaign_id=row["id"],
            name=row["name"],
            created_at=row["created_at"],
            battle_count=row["battle_count"],
        )

    def list_campaigns(self) -> list[CampaignMeta]:
        rows = self._conn.execute("SELECT * FROM campaigns ORDER BY id DESC").fetchall()
        return [
            CampaignMeta(
                campaign_id=r["id"],
                name=r["name"],
                created_at=r["created_at"],
                battle_count=r["battle_count"],
            )
            for r in rows
        ]

    def increment_battle_count(self, campaign_id: int) -> None:
        self._conn.execute(
            "UPDATE campaigns SET battle_count = battle_count + 1 WHERE id = ?",
            (campaign_id,),
        )
        self._conn.commit()

    def save_lore(self, campaign_id: int, lore_dict: dict) -> None:
        """Persist lore JSON for a campaign."""
        self._conn.execute(
            "UPDATE campaigns SET lore_json = ? WHERE id = ?",
            (json.dumps(lore_dict), campaign_id),
        )
        self._conn.commit()

    def load_lore(self, campaign_id: int) -> dict | None:
        """Load persisted lore for a campaign, or None if not yet generated."""
        row = self._conn.execute(
            "SELECT lore_json FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if row and row["lore_json"]:
            return json.loads(row["lore_json"])
        return None

    def delete_campaign(self, campaign_id: int) -> None:
        """Delete a campaign and all associated data."""
        for table in ("memories", "relationships", "battles", "roster", "campaigns"):
            col = "campaign_id" if table != "campaigns" else "id"
            self._conn.execute(f"DELETE FROM {table} WHERE {col} = ?", (campaign_id,))
        self._conn.commit()
        log.info("Deleted campaign id=%d", campaign_id)

    # -- Roster --------------------------------------------------------------

    def save_roster(self, campaign_id: int, roster: list[RosterEntry]) -> None:
        """Upsert the full roster for a campaign."""
        for r in roster:
            self._conn.execute(
                """INSERT OR REPLACE INTO roster
                   (campaign_id, agent_id, name, combat_class, sprite,
                    backstory, personality,
                    alive, xp, level, atk, mgk, spd, con, hit,
                    attack_range, abilities, limit_break, morality, order_value)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    campaign_id,
                    r.agent_id,
                    r.name,
                    r.combat_class,
                    r.sprite,
                    r.backstory,
                    json.dumps(r.personality_traits),
                    int(r.alive),
                    r.xp,
                    r.level,
                    r.atk,
                    r.mgk,
                    r.spd,
                    r.con,
                    r.hit,
                    r.attack_range,
                    json.dumps(r.abilities),
                    json.dumps(r.limit_break) if r.limit_break else None,
                    r.morality,
                    r.order_value,
                ),
            )
        self._conn.commit()

    def load_roster(self, campaign_id: int) -> list[RosterEntry]:
        rows = self._conn.execute(
            "SELECT * FROM roster WHERE campaign_id = ? ORDER BY agent_id",
            (campaign_id,),
        ).fetchall()
        return [_row_to_roster_entry(r) for r in rows]

    def load_alive_roster(self, campaign_id: int) -> list[RosterEntry]:
        rows = self._conn.execute(
            "SELECT * FROM roster WHERE campaign_id = ? AND alive = 1 ORDER BY agent_id",
            (campaign_id,),
        ).fetchall()
        return [_row_to_roster_entry(r) for r in rows]

    # -- Battles -------------------------------------------------------------

    def save_battle(self, campaign_id: int, record: BattleRecord) -> None:
        self._conn.execute(
            """INSERT INTO battles
               (campaign_id, battle_num, winner_ids, death_ids, rounds,
                xp_awards, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                campaign_id,
                record.battle_num,
                json.dumps(record.winner_ids),
                json.dumps(record.death_ids),
                record.rounds,
                json.dumps(record.xp_awards),
                record.timestamp,
            ),
        )
        self._conn.commit()

    def load_battles(self, campaign_id: int) -> list[BattleRecord]:
        rows = self._conn.execute(
            "SELECT * FROM battles WHERE campaign_id = ? ORDER BY battle_num",
            (campaign_id,),
        ).fetchall()
        return [
            BattleRecord(
                battle_num=r["battle_num"],
                winner_ids=json.loads(r["winner_ids"]),
                death_ids=json.loads(r["death_ids"]),
                rounds=r["rounds"],
                timestamp=r["timestamp"],
                xp_awards=json.loads(r["xp_awards"]),
            )
            for r in rows
        ]

    # -- Memories ------------------------------------------------------------

    def save_memories(self, campaign_id: int, memories: list[SerializedMemory]) -> None:
        """Replace all stored memories for agents in this campaign."""
        # Collect agent_ids being saved so we only delete those
        agent_ids = {m.agent_id for m in memories}
        for aid in agent_ids:
            self._conn.execute(
                "DELETE FROM memories WHERE campaign_id = ? AND agent_id = ?",
                (campaign_id, aid),
            )
        for m in memories:
            self._conn.execute(
                """INSERT INTO memories
                   (campaign_id, agent_id, description, poignancy,
                    memory_type, turn_created)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    campaign_id,
                    m.agent_id,
                    m.description,
                    m.poignancy,
                    m.memory_type,
                    m.turn_created,
                ),
            )
        self._conn.commit()

    def load_memories(
        self, campaign_id: int, agent_id: str | None = None
    ) -> list[SerializedMemory]:
        if agent_id:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE campaign_id = ? AND agent_id = ?",
                (campaign_id, agent_id),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchall()
        return [
            SerializedMemory(
                agent_id=r["agent_id"],
                description=r["description"],
                poignancy=r["poignancy"],
                memory_type=r["memory_type"],
                turn_created=r["turn_created"],
            )
            for r in rows
        ]

    # -- Relationships -------------------------------------------------------

    def save_relationships(
        self, campaign_id: int, rels: list[SerializedRelationship]
    ) -> None:
        # Collect owner_ids being saved
        owner_ids = {r.owner_id for r in rels}
        for oid in owner_ids:
            self._conn.execute(
                "DELETE FROM relationships WHERE campaign_id = ? AND owner_id = ?",
                (campaign_id, oid),
            )
        for r in rels:
            self._conn.execute(
                """INSERT INTO relationships
                   (campaign_id, owner_id, target_id, target_name,
                    disposition, trust, betrayal_count, alliance_declared)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    campaign_id,
                    r.owner_id,
                    r.target_id,
                    r.target_name,
                    r.disposition,
                    r.trust,
                    r.betrayal_count,
                    int(r.alliance_declared),
                ),
            )
        self._conn.commit()

    def load_relationships(
        self, campaign_id: int, owner_id: str | None = None
    ) -> list[SerializedRelationship]:
        if owner_id:
            rows = self._conn.execute(
                "SELECT * FROM relationships WHERE campaign_id = ? AND owner_id = ?",
                (campaign_id, owner_id),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM relationships WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchall()
        return [
            SerializedRelationship(
                owner_id=r["owner_id"],
                target_id=r["target_id"],
                target_name=r["target_name"],
                disposition=r["disposition"],
                trust=r["trust"],
                betrayal_count=r["betrayal_count"],
                alliance_declared=bool(r["alliance_declared"]),
            )
            for r in rows
        ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_roster_entry(r: sqlite3.Row) -> RosterEntry:
    lb_raw = r["limit_break"] if "limit_break" in r.keys() else None
    return RosterEntry(
        agent_id=r["agent_id"],
        name=r["name"],
        combat_class=r["combat_class"],
        sprite=r["sprite"],
        backstory=r["backstory"],
        personality_traits=json.loads(r["personality"]),
        alive=bool(r["alive"]),
        xp=r["xp"],
        level=r["level"],
        atk=r["atk"],
        mgk=r["mgk"],
        spd=r["spd"],
        con=r["con"],
        hit=r["hit"],
        attack_range=r["attack_range"],
        abilities=json.loads(r["abilities"]),
        limit_break=json.loads(lb_raw) if lb_raw else None,
        morality=r["morality"],
        order_value=r["order_value"],
    )
