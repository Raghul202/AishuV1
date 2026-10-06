"""One global policy for Discord application-command installation and contexts.

Commands are created by the existing cogs.  This module applies their visibility
once, immediately before the single global tree sync.
"""
from __future__ import annotations

from discord import app_commands

from commands.registry import COMMANDS, PermLevel

# This panel needs a guild object even though it is owner-only.
_EXTRA_GUILD_ONLY = {"aishu_panel"}
# Registered outside the metadata registry; it is a privileged diagnostics command.
_EXTRA_PRIVILEGED = {"refreshmodel"}


def configure_global_commands(tree: app_commands.CommandTree) -> dict[str, int]:
    """Apply Discord's current global command contexts exactly once.

    Public commands support Guild, bot DM, and private/group DM and can be
    installed both to guilds and individual users.  Guild-dependent commands
    are deliberately excluded from DMs and user installs.  Owner/developer
    commands can be used in a guild or bot DM but are not user-installable.
    """
    seen: set[str] = set()
    counts = {"public": 0, "guild_only": 0, "privileged": 0}

    for command in tree.get_commands():
        key = str(command.name)
        if key in seen:
            # CommandTree normally prevents this. Keep a defensive single path
            # if a future cog attempts to register a duplicate.
            tree.remove_command(command.name)
            continue
        seen.add(key)

        meta = COMMANDS.get(command.name)
        guild_only = command.name in _EXTRA_GUILD_ONLY or bool(meta and meta.guild_only)
        privileged = command.name in _EXTRA_PRIVILEGED or bool(meta and meta.perm != PermLevel.PUBLIC)

        if guild_only:
            app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)(command)
            app_commands.allowed_installs(guilds=True, users=False)(command)
            counts["guild_only"] += 1
        elif privileged:
            app_commands.allowed_contexts(guilds=True, dms=True, private_channels=False)(command)
            app_commands.allowed_installs(guilds=True, users=False)(command)
            counts["privileged"] += 1
        else:
            app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)(command)
            app_commands.allowed_installs(guilds=True, users=True)(command)
            counts["public"] += 1

    return counts
