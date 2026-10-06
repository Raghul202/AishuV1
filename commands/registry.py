"""
commands/registry.py — Central Command Registry.

Defines all commands with their metadata, permission levels,
aliases, and descriptions. This is the single source of truth
for what commands exist and who can use them.
"""

from dataclasses import dataclass, field
from enum import IntEnum


class PermLevel(IntEnum):
    """Permission levels from lowest to highest."""
    PUBLIC     = 0    # any user
    MODERATOR  = 1    # manage_messages permission
    GUILD_ADMIN= 2    # administrator permission
    BOT_OWNER  = 3    # the bot owner ID
    DEVELOPER  = 4    # same as owner but for dev tools


@dataclass
class CommandMeta:
    """Metadata for a single command."""
    name:        str
    description: str
    aliases:     list[str]  = field(default_factory=list)
    perm:        PermLevel  = PermLevel.PUBLIC
    slash:       bool       = True    # available as slash command
    prefix:      bool       = True    # available as prefix command
    guild_only:  bool       = False   # only works in servers (not DMs)
    cooldown_s:  float      = 3.0     # per-user cooldown in seconds
    category:    str        = "misc"


# ─── Complete Command Registry ────────────────────────────────────────────────

COMMANDS: dict[str, CommandMeta] = {

    # ── Chat / Interaction ────────────────────────────────────────────────────

    "chat": CommandMeta(
        name        = "chat",
        description = "Chat with Aishu",
        aliases     = ["aishu", "ai", "ask", "a"],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "chat",
        cooldown_s  = 3.0,
    ),

    "aishu": CommandMeta(
        name        = "aishu",
        description = "Chat with Aishu",
        aliases     = ["ai", "ask", "a", "chat"],
        perm        = PermLevel.PUBLIC,
        slash       = False,
        prefix      = True,
        category    = "chat",
        cooldown_s  = 3.0,
    ),

    "image": CommandMeta(
        name        = "image",
        description = "Create an image from a prompt",
        aliases     = ["draw", "imagine"],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "chat",
        cooldown_s  = 12.0,
    ),

    "analyzeimage": CommandMeta(
        name        = "analyzeimage",
        description = "Have Aishu look at and analyze an image",
        aliases     = ["analyze", "aiimage", "scanimage"],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "chat",
        cooldown_s  = 8.0,
    ),

    "continue": CommandMeta(
        name        = "continue",
        description = "Continue the conversation or active roleplay story",
        aliases     = ["cont"],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "chat",
        cooldown_s  = 3.0,
    ),

    # ── Memory Commands ───────────────────────────────────────────────────────

    "memories": CommandMeta(
        name        = "memories",
        description = "See what Aishu remembers about you",
        aliases     = ["memory", "mem", "know"],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "memory",
        cooldown_s  = 5.0,
    ),

    "remember": CommandMeta(
        name        = "remember",
        description = "Tell Aishu a specific fact or preference to remember",
        aliases     = ["rem"],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "memory",
        cooldown_s  = 3.0,
    ),

    "memorysearch": CommandMeta(
        name        = "memorysearch",
        description = "Search through your memories with Aishu",
        aliases     = ["memsearch"],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "memory",
        cooldown_s  = 4.0,
    ),

    "forget": CommandMeta(
        name        = "forget",
        description = "Make Aishu forget a topic or keyword",
        aliases     = ["remove"],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "memory",
        cooldown_s  = 5.0,
    ),

    "clear": CommandMeta(
        name        = "clear",
        description = "Clear your own STM + LTM memory with Aishu",
        aliases     = [],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "memory",
        cooldown_s  = 10.0,
    ),

    "export": CommandMeta(
        name        = "export",
        description = "Download your Aishu memory as a JSON file",
        aliases     = [],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "memory",
        cooldown_s  = 10.0,
    ),

    # ── Social / Companion Commands ───────────────────────────────────────────

    "profile": CommandMeta(
        name        = "profile",
        description = "View your (or someone's) Aishu profile and bond",
        aliases     = ["p", "user"],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "social",
        cooldown_s  = 5.0,
    ),

    "bond": CommandMeta(
        name        = "bond",
        description = "Check your relationship bond details, trust, and warmth",
        aliases     = [],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "social",
        cooldown_s  = 4.0,
    ),

    "relationship": CommandMeta(
        name        = "relationship",
        description = "Check your relationship level with Aishu",
        aliases     = ["rel"],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "social",
        cooldown_s  = 5.0,
    ),

    "streak": CommandMeta(
        name        = "streak",
        description = "See your conversation streak with Aishu",
        aliases     = ["s"],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "social",
        cooldown_s  = 5.0,
    ),

    "leaderboard": CommandMeta(
        name        = "leaderboard",
        description = "Aishu's favorite people in this server",
        aliases     = ["lb", "top", "fav", "favorites"],
        perm        = PermLevel.PUBLIC,
        guild_only  = True,
        slash       = True,
        prefix      = True,
        category    = "social",
        cooldown_s  = 5.0,
    ),

    "mood": CommandMeta(
        name        = "mood",
        description = "Check Aishu's current mood, energy, and vibe",
        aliases     = ["feelings", "vibe"],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "social",
        cooldown_s  = 3.0,
    ),

    "diary": CommandMeta(
        name        = "diary",
        description = "Read a sweet page from Aishu's personal diary",
        aliases     = [],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "social",
        cooldown_s  = 5.0,
    ),

    "moments": CommandMeta(
        name        = "moments",
        description = "View cherished moments and milestones between you and Aishu",
        aliases     = [],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "social",
        cooldown_s  = 4.0,
    ),

    "persona": CommandMeta(
        name        = "persona",
        description = "Inspect Aishu's personality card, likes, and identity",
        aliases     = [],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "social",
        cooldown_s  = 4.0,
    ),

    "afk": CommandMeta(
        name        = "afk",
        description = "Set yourself as AFK (persists across restarts)",
        aliases     = [],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "social",
        cooldown_s  = 5.0,
    ),

    "quietmode": CommandMeta(
        name        = "quietmode",
        description = "Toggle quiet mode (Aishu only replies when directly mentioned)",
        aliases     = ["quiet"],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "social",
        cooldown_s  = 4.0,
    ),

    # ── Info Commands ─────────────────────────────────────────────────────────

    "ping": CommandMeta(
        name        = "ping",
        description = "Check Aishu's latency",
        aliases     = ["latency"],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "info",
        cooldown_s  = 5.0,
    ),

    "help": CommandMeta(
        name        = "help",
        description = "Show all available commands by category",
        aliases     = ["h", "commands", "cmds"],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "info",
        cooldown_s  = 5.0,
    ),

    "botinfo": CommandMeta(
        name        = "botinfo",
        description = "Show information about Aishu",
        aliases     = ["info", "about"],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "info",
        cooldown_s  = 10.0,
    ),

    "serverinfo": CommandMeta(
        name        = "serverinfo",
        description = "Show server information",
        aliases     = ["server", "guildinfo"],
        perm        = PermLevel.PUBLIC,
        guild_only  = True,
        slash       = True,
        prefix      = True,
        category    = "info",
        cooldown_s  = 10.0,
    ),

    "family": CommandMeta(
        name        = "family",
        description = "Learn about Aishu's family (RavenAI and Mia)",
        aliases     = [],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "info",
        cooldown_s  = 5.0,
    ),

    "models": CommandMeta(
        name        = "models",
        description = "Show AI models available to Aishu across providers",
        aliases     = [],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "info",
        cooldown_s  = 5.0,
    ),

    "privacy": CommandMeta(
        name        = "privacy",
        description = "See what data Aishu stores about you and privacy controls",
        aliases     = [],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "info",
        cooldown_s  = 5.0,
    ),

    # ── Roleplay Commands (Partner DM Only) ───────────────────────────────────

    "rp_status": CommandMeta(
        name        = "rp_status",
        description = "Check active roleplay session status and story (Partner only)",
        aliases     = [],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "roleplay",
        cooldown_s  = 5.0,
    ),

    "rp_history": CommandMeta(
        name        = "rp_history",
        description = "View your past archived roleplay sessions (Partner only)",
        aliases     = [],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "roleplay",
        cooldown_s  = 5.0,
    ),

    "rp_end": CommandMeta(
        name        = "rp_end",
        description = "End the active roleplay session (Partner only)",
        aliases     = [],
        perm        = PermLevel.PUBLIC,
        slash       = True,
        prefix      = True,
        category    = "roleplay",
        cooldown_s  = 5.0,
    ),

    # ── Moderation Commands ───────────────────────────────────────────────────

    "purge": CommandMeta(
        name        = "purge",
        description = "Delete a number of messages from the channel (1-100)",
        aliases     = [],
        perm        = PermLevel.MODERATOR,
        slash       = True,
        prefix      = True,
        guild_only  = True,
        category    = "moderation",
        cooldown_s  = 5.0,
    ),

    # ── Admin Commands ────────────────────────────────────────────────────────

    "setchannel": CommandMeta(
        name        = "setchannel",
        description = "Set channel where Aishu auto-replies (Admin)",
        aliases     = [],
        perm        = PermLevel.GUILD_ADMIN,
        slash       = True,
        prefix      = True,
        guild_only  = True,
        category    = "admin",
        cooldown_s  = 5.0,
    ),

    "removechannel": CommandMeta(
        name        = "removechannel",
        description = "Disable Aishu's auto-reply channel (Admin)",
        aliases     = [],
        perm        = PermLevel.GUILD_ADMIN,
        slash       = True,
        prefix      = True,
        guild_only  = True,
        category    = "admin",
        cooldown_s  = 5.0,
    ),

    "announce": CommandMeta(
        name        = "announce",
        description = "Make Aishu send an announcement embed (Admin)",
        aliases     = [],
        perm        = PermLevel.GUILD_ADMIN,
        slash       = True,
        prefix      = True,
        guild_only  = True,
        category    = "admin",
        cooldown_s  = 10.0,
    ),

    "guildconfig": CommandMeta(
        name        = "guildconfig",
        description = "View or check guild configuration settings (Admin)",
        aliases     = [],
        perm        = PermLevel.GUILD_ADMIN,
        slash       = True,
        prefix      = True,
        guild_only  = True,
        category    = "admin",
        cooldown_s  = 5.0,
    ),

    # ── Owner Commands ────────────────────────────────────────────────────────

    "aishu_panel": CommandMeta(
        name        = "aishu_panel",
        description = "Open Aishu's full settings panel (Owner only)",
        aliases     = ["panel"],
        perm        = PermLevel.BOT_OWNER,
        slash       = True,
        prefix      = True,
        guild_only  = True,
        category    = "owner",
        cooldown_s  = 0.0,
    ),

    "setprofile": CommandMeta(
        name        = "setprofile",
        description = "Open Aishu's Discord profile studio (Owner only)",
        aliases     = ["aishuprofile"],
        perm        = PermLevel.BOT_OWNER,
        slash       = True,
        prefix      = True,
        category    = "owner",
        cooldown_s  = 5.0,
    ),

    "setmood": CommandMeta(
        name        = "setmood",
        description = "Force Aishu's mood state (Owner only)",
        aliases     = [],
        perm        = PermLevel.BOT_OWNER,
        slash       = True,
        prefix      = True,
        category    = "owner",
        cooldown_s  = 0.0,
    ),

    "setstatus": CommandMeta(
        name        = "setstatus",
        description = "Change the bot's status text (Owner only)",
        aliases     = [],
        perm        = PermLevel.BOT_OWNER,
        slash       = True,
        prefix      = True,
        category    = "owner",
        cooldown_s  = 0.0,
    ),

    "setlover": CommandMeta(
        name        = "setlover",
        description = "Set Aishu's special person (Owner only)",
        aliases     = [],
        perm        = PermLevel.BOT_OWNER,
        slash       = True,
        prefix      = True,
        category    = "owner",
        cooldown_s  = 0.0,
    ),

    "setpartner": CommandMeta(
        name        = "setpartner",
        description = "Set Aishu's life partner (Owner only)",
        aliases     = [],
        perm        = PermLevel.BOT_OWNER,
        slash       = True,
        prefix      = True,
        category    = "owner",
        cooldown_s  = 0.0,
    ),

    "clearpartner": CommandMeta(
        name        = "clearpartner",
        description = "Clear Aishu's life partner (Owner only)",
        aliases     = [],
        perm        = PermLevel.BOT_OWNER,
        slash       = True,
        prefix      = True,
        category    = "owner",
        cooldown_s  = 0.0,
    ),

    "stats": CommandMeta(
        name        = "stats",
        description = "Show Aishu's runtime metrics and model stats (Owner only)",
        aliases     = [],
        perm        = PermLevel.BOT_OWNER,
        slash       = True,
        prefix      = True,
        category    = "owner",
        cooldown_s  = 5.0,
    ),

    "inspect": CommandMeta(
        name        = "inspect",
        description = "Debug Aishu's AI context for a user (Owner only)",
        aliases     = [],
        perm        = PermLevel.BOT_OWNER,
        slash       = True,
        prefix      = True,
        category    = "owner",
        cooldown_s  = 5.0,
    ),

    "adminreset": CommandMeta(
        name        = "adminreset",
        description = "Wipe ALL users' memory globally (Owner only)",
        aliases     = [],
        perm        = PermLevel.BOT_OWNER,
        slash       = True,
        prefix      = True,
        category    = "owner",
        cooldown_s  = 0.0,
    ),

    # ── Developer Commands ────────────────────────────────────────────────────

    "refreshmodel": CommandMeta(
        name        = "refreshmodel",
        description = "Live probe and benchmark all AI models (Owner/Dev)",
        aliases     = [],
        perm        = PermLevel.DEVELOPER,
        slash       = True,
        prefix      = True,
        category    = "developer",
        cooldown_s  = 30.0,
    ),

    "probe": CommandMeta(
        name        = "probe",
        description = "Run AI model diagnostics probe (Developer)",
        aliases     = [],
        perm        = PermLevel.DEVELOPER,
        slash       = False,
        prefix      = True,
        category    = "developer",
        cooldown_s  = 30.0,
    ),

    "brain": CommandMeta(
        name        = "brain",
        description = "Show Brain system status JSON (Developer)",
        aliases     = [],
        perm        = PermLevel.DEVELOPER,
        slash       = False,
        prefix      = True,
        category    = "developer",
        cooldown_s  = 5.0,
    ),

    "memorycheck": CommandMeta(
        name        = "memorycheck",
        description = "Inspect any user's raw memory (Developer)",
        aliases     = ["memcheck"],
        perm        = PermLevel.DEVELOPER,
        slash       = False,
        prefix      = True,
        category    = "developer",
        cooldown_s  = 5.0,
    ),

    "modelstatus": CommandMeta(
        name        = "modelstatus",
        description = "Show persistent model ranking report (Developer)",
        aliases     = [],
        perm        = PermLevel.DEVELOPER,
        slash       = False,
        prefix      = True,
        category    = "developer",
        cooldown_s  = 5.0,
    ),

    "rankingsave": CommandMeta(
        name        = "rankingsave",
        description = "Force-save model rankings to disk (Developer)",
        aliases     = [],
        perm        = PermLevel.DEVELOPER,
        slash       = False,
        prefix      = True,
        category    = "developer",
        cooldown_s  = 5.0,
    ),
}


def get_by_alias(alias: str) -> CommandMeta | None:
    """Look up a CommandMeta by name or alias."""
    alias = alias.lower()
    for meta in COMMANDS.values():
        if alias == meta.name or alias in meta.aliases:
            return meta
    return None


def get_by_category(category: str) -> list[CommandMeta]:
    """Return all commands in a category."""
    return [m for m in COMMANDS.values() if m.category == category]
