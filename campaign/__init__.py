"""Campaign mode — persistent sandbox with XP, leveling, and memory carry-over."""

from campaign.manager import CampaignManager, roster_entry_from_agent
from campaign.models import BattleRecord, CampaignMeta, RosterEntry
from campaign.persistence import CampaignDB

__all__ = [
    "CampaignDB",
    "CampaignManager",
    "CampaignMeta",
    "BattleRecord",
    "RosterEntry",
    "roster_entry_from_agent",
]
