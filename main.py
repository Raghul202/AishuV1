"""
main.py — AIshu Discord Bot Entry Point

Run with:  python main.py

Startup sequence:
  1. validate_config() — exits with clear error if secrets are missing
  2. ensure_directories() — creates data/logs dirs on first run
  3. Load cogs
  4. on_ready → sync slash commands, set status
  5. on_message → route to brain_router via do_reply()
"""

import asyncio
import importlib.util
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def ensure_requirements():
    """Report missing runtime dependencies; deployment installs requirements.txt."""
    required = {
        "discord": "discord.py>=2.4.0",
        "requests": "requests>=2.31.0",
        "aiohttp": "aiohttp>=3.9.0",
        "dotenv": "python-dotenv>=1.0.0",
        "groq": "groq>=0.9.0",
        "openai": "openai>=1.30.0",
    }
    missing = []
    for module_name, spec in required.items():
        if importlib.util.find_spec(module_name) is None:
            missing.append(spec)
    if missing:
        print(
            "❌ Missing required dependencies: " + ", ".join(missing)
            + ". Install the packages listed in requirements.txt before starting Aishu.",
            file=sys.stderr,
        )
        sys.exit(1)


ensure_requirements()

import discord
from discord.ext import commands

import config.settings as cfg
from config.settings import validate_config, ensure_directories
from brain.router import brain_router
from core.memory.memory_manager import memory_manager
from core.personality.aishu_state import aishu_state
from core.schemas import FAIL_RATE_LIMITED, get_failure_message
from utilities.helpers import clean_mention
from utilities.ratelimit import limiter
from utilities.logger import get_logger
from commands.chat_cog import do_reply
from commands.application_command_config import configure_global_commands
from web.server import DashboardServer

log = get_logger("main")

# Per-guild per-user cooldown tracker {"guild_id:user_id": monotonic_timestamp}
_guild_cooldowns: dict = {}


def create_bot() -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members         = True
    return commands.Bot(
        command_prefix   = cfg.PREFIX,
        intents          = intents,
        help_command     = None,
        case_insensitive = True,
    )


async def main():
    # ── Startup validation ────────────────────────────────────────────────────
    errors = validate_config()
    if errors:
        print("\n❌ Configuration errors found:")
        for e in errors:
            print(f"   • {e}")
        print("\nOpen config/settings.py and fill in your credentials at the top of the file.\n")
        sys.exit(1)

    ensure_directories()

    bot = create_bot()
    commands_synced = False
    command_sync_lock = asyncio.Lock()

    # ── Events ────────────────────────────────────────────────────────────────

    @bot.event
    async def on_ready():
        nonlocal commands_synced
        await bot.change_presence(activity=discord.Game(name=aishu_state.status_text))
        # on_ready fires again after a gateway reconnect. Re-syncing global
        # commands on every reconnect wastes Discord API quota and can delay
        # propagation, so a running process performs this exactly once.
        async with command_sync_lock:
            if not commands_synced:
                try:
                    synced = await bot.tree.sync()
                    commands_synced = True
                    log.info(f"Synced {len(synced)} slash commands")
                except Exception as e:
                    log.warning(f"Slash sync failed: {e}")

        log.info(
            f"Online: {bot.user} | Guilds: {len(bot.guilds)} "
            f"| Users: {memory_manager.user_count()}"
        )
        mood_label = aishu_state.mood.mood
        mood_emoji = aishu_state.mood.emoji
        lover      = aishu_state.lover_name or "none"
        partner    = aishu_state.partner_name or "none"
        mem_status = "enabled ✅" if memory_manager.is_memory_available() else "DEGRADED ❌"
        print(f"\n{'═'*48}")
        print(f"          Aishu is online ♡")
        print(f"      Ready to chat and stay close~")
        print(f"{'─'*48}")
        print(f"  Bot     : {bot.user}")
        print(f"  Guilds  : {len(bot.guilds)}")
        print(f"  Users   : {memory_manager.user_count()}")
        print(f"  Mood    : {mood_label} {mood_emoji}")
        print(f"  Partner : {partner}")
        print(f"  Lover   : {lover}")
        print(f"  Memory  : {mem_status}")
        print(f"{'═'*48}\n")

    @bot.event
    async def on_command_error(ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("you don't have permission for that 🚫", delete_after=5)
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"slow down! wait {error.retry_after:.1f}s 😅", delete_after=4)
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"missing: `{error.param.name}`", delete_after=5)
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"invalid argument: {error}", delete_after=5)
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send("this command only works in servers!", delete_after=5)
        else:
            log.error(f"Command error [{ctx.command}]: {error}")
            try:
                await ctx.send("something went wrong while running that command 😅", delete_after=5)
            except Exception:
                pass

    @bot.event
    async def on_message(message: discord.Message):
        """
        Central message handler.

        Routing:
          DM → always respond if not bot / not rate-limited
          Guild → respond only if in auto-channel OR @mentioned
          Commands → process_commands() handles first
        """
        if message.author.bot:
            return

        uid          = message.author.id
        username     = str(message.author)
        display_name = message.author.display_name

        # ── Non-Guild: 1-on-1 DM or Group DM ──────────────────────────────────
        if not message.guild:
            text = message.content.strip()
            if not text:
                return

            # Prefix commands work everywhere
            if text.startswith(cfg.PREFIX):
                await bot.process_commands(message)
                return

            is_group_dm = (
                isinstance(message.channel, getattr(discord, "GroupChannel", ()))
                or type(message.channel).__name__ == "GroupChannel"
                or (hasattr(message.channel, "recipients") and len(getattr(message.channel, "recipients", [])) > 1)
            )
            if is_group_dm:
                # In Group DMs with multiple people: only respond when mentioned or addressed by name
                mentioned = bot.user in message.mentions
                name_addressed = bool(re.search(r"\baishu\b", text, re.IGNORECASE))
                if not (mentioned or name_addressed):
                    return  # Avoid interrupting conversations between other people

                clean_text = clean_mention(text, bot.user.id)
                clean_text = re.sub(r"^(?:hey\s+)?aishu\b[,:\s]*", "", clean_text, flags=re.IGNORECASE).strip()
                if not clean_text:
                    clean_text = "hey"

                if limiter.is_limited(uid):
                    fb = get_failure_message(FAIL_RATE_LIMITED, aishu_state.mood.mood)
                    await message.channel.send(fb, delete_after=4)
                    return

                # In group DMs, is_dm=False protects private partner memories from leaking
                await do_reply(
                    message=message, user_id=uid, guild_id=0,
                    username=username, display_name=display_name,
                    text=clean_text, is_dm=False, is_mention=True,
                )
                return

            # 1-on-1 direct DM
            if memory_manager.is_quiet(message.channel.id):
                # If quiet mode is toggled on in this DM, only respond if addressed
                mentioned = bot.user in message.mentions or bool(re.search(r"\baishu\b", text, re.IGNORECASE))
                if not mentioned:
                    return

            if limiter.is_limited(uid):
                fb = get_failure_message(FAIL_RATE_LIMITED, aishu_state.mood.mood)
                await message.channel.send(fb, delete_after=4)
                return
            await do_reply(
                message=message, user_id=uid, guild_id=0,
                username=username, display_name=display_name,
                text=text, is_dm=True,
            )
            return

        # ── Guild ─────────────────────────────────────────────────────────────
        # Prefix commands are exclusively handled by discord.py.  Returning here
        # prevents a mention in the same message from producing a second reply.
        if message.content.startswith(cfg.PREFIX):
            await bot.process_commands(message)
            return

        guild_id   = message.guild.id
        auto_ch    = aishu_state.get_auto_channel(guild_id)
        mentioned  = bot.user in message.mentions
        quiet      = memory_manager.is_quiet(message.channel.id, guild_id)
        in_auto_ch = (message.channel.id == auto_ch) and not quiet

        if not (in_auto_ch or mentioned):
            return

        text = clean_mention(message.content, bot.user.id)
        if not text or text.startswith(cfg.PREFIX):
            return

        # ── GuildConfig enforcement ───────────────────────────────────────────
        gc = memory_manager.get_guild_config(guild_id, message.guild.name)

        # Per-guild cooldown (overrides global limiter when stricter)
        guild_cd = gc.cooldown_seconds
        if guild_cd > 0:
            _cd_key = f"{guild_id}:{uid}"
            _now    = time.monotonic()
            for key, stamp in tuple(_guild_cooldowns.items()):
                if _now - stamp > 60.0:
                    _guild_cooldowns.pop(key, None)
            _last   = _guild_cooldowns.get(_cd_key, 0.0)
            if _now - _last < guild_cd:
                remaining = round(guild_cd - (_now - _last), 1)
                fb = get_failure_message(FAIL_RATE_LIMITED, aishu_state.mood.mood)
                await message.reply(
                    f"{fb} ({remaining}s)", delete_after=4, mention_author=False)
                return
            _guild_cooldowns[_cd_key] = _now

        # Global rate limiter
        if limiter.is_limited(uid):
            fb = get_failure_message(FAIL_RATE_LIMITED, aishu_state.mood.mood)
            await message.reply(fb, delete_after=4, mention_author=False)
            return

        await do_reply(
            message=message, user_id=uid, guild_id=guild_id,
            username=username, display_name=display_name,
            text=text, is_mention=mentioned,
            guild_config=gc,
        )

    @bot.event
    async def on_guild_join(guild: discord.Guild):
        memory_manager.get_guild_config(guild.id, guild.name)
        log.info(f"Joined guild: {guild.name} ({guild.id})")

    @bot.event
    async def on_guild_remove(guild: discord.Guild):
        log.info(f"Left guild: {guild.name} ({guild.id})")


    # ── Load cogs ─────────────────────────────────────────────────────────────
    await bot.load_extension("commands.chat_cog")
    await bot.load_extension("commands.admin_cog")
    await bot.load_extension("commands.refresh_model_cog")  # ← add this
    command_counts = configure_global_commands(bot.tree)
    log.info("Configured global command contexts: %s", command_counts)
    log.info("All cogs loaded")

    # ── Dashboard ─────────────────────────────────────────────────────────────
    dashboard = DashboardServer(bot)
    await dashboard.start()

    # ── Start ─────────────────────────────────────────────────────────────────
    try:
        await bot.start(cfg.DISCORD_TOKEN)
    except discord.LoginFailure:
        print("❌ Invalid Discord token! Check config/settings.py")
        sys.exit(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await dashboard.stop()
        if not bot.is_closed():
            await bot.close()
        memory_manager.flush_all()
        aishu_state.flush()
        print(f"\n{'─'*48}")
        print(f"  Aishu is going offline...")
        print(f"  Goodbye bro ♡")
        print(f"  Shutdown completed cleanly.")
        print(f"{'─'*48}\n")
        log.info("Shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
