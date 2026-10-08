"""
commands/chat_cog.py — Chat, Memory, Social, and Info commands.

Prefix: !aishu, !memories, !forget, !clear, !profile, !leaderboard,
        !mood, !relationship, !streak, !ping, !help, !botinfo,
        !serverinfo, !afk, !purge, !export

Slash:  /chat, /memories, /forget, /clear, /profile, /leaderboard,
        /mood, /relationship, /streak, /export, /ping, /botinfo,
        /serverinfo
"""

import asyncio
import io
import json
import random
import time
import platform
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import config.settings as cfg
from brain.router import brain_router
from brain.image_generator import image_generator
from core.afk_manager import afk_manager
from core.memory.memory_manager import memory_manager
from core.personality.aishu_state import aishu_state
from core.schemas import FAIL_RATE_LIMITED, get_failure_message
from utilities.helpers import relationship_label, is_preference, get_theme_color
from utilities.ratelimit import limiter
from utilities.logger import get_logger

log = get_logger("commands.chat")

MEDALS = ["🥇", "🥈", "🥉"]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _embed(color: int, title: str, desc: str = "") -> discord.Embed:
    embed = discord.Embed(title=title, description=desc, color=color, timestamp=datetime.now(timezone.utc))
    embed.set_footer(text="Aishu ✿")
    return embed


def _image_result_embed(bot: commands.Bot, image, prompt: str, duration: float = 0.0) -> discord.Embed:
    """Consistent, compact presentation for every generated image."""
    embed = discord.Embed(
        title="✦ Aishu made something for you",
        description="your little idea, turned into a picture 🌸",
        color=get_theme_color(),
        timestamp=datetime.now(timezone.utc),
    )
    if bot.user:
        embed.set_author(name=aishu_state.name, icon_url=bot.user.display_avatar.url)
        embed.set_thumbnail(url=bot.user.display_avatar.url)
    embed.add_field(name="Prompt", value=prompt.strip()[:500] or "(no prompt)", inline=False)
    embed.add_field(name="Generator", value=f"`{image.provider}`", inline=True)
    embed.add_field(name="Format", value=f"`{image.filename.rsplit('.', 1)[-1].upper()}`", inline=True)
    if duration > 0:
        embed.add_field(name="Time", value=f"`{duration:.1f}s`", inline=True)
    embed.set_footer(text="Aishu ✿ image generation")
    return embed


async def do_reply(
    message: discord.Message,
    user_id: int,
    guild_id: int,
    username: str,
    display_name: str,
    text: str,
    is_dm: bool = False,
    is_mention: bool = False,
    guild_config=None,
):
    """
    Central reply flow.
    Calls brain_router.process(), handles ExecutionResult, sends chunks.
    guild_config is an optional GuildConfig — passed from main.py guild path.
    """
    result = await brain_router.process(
        user_id      = user_id,
        username     = username,
        display_name = display_name,
        text         = text,
        guild_id     = guild_id,
        channel_id   = message.channel.id,
        is_dm        = is_dm,
        is_mention   = is_mention,
        guild_config = guild_config,
    )

    if not result.chunks:
        return

    # Log pipeline result
    if result.success:
        model_short = result.model_used.split("/")[-1][:25] if "/" in result.model_used else result.model_used[:25]
        log.debug(f"[{result.request_id}] Reply sent via {model_short} in {result.latency_ms:.0f}ms")
    else:
        log.warning(f"[{result.request_id}] Sending fallback: {result.failure_kind}")

    # Typing simulation based on response length
    total_chars = sum(len(c) for c in result.chunks)
    delay = random.uniform(cfg.TYPING_MIN, cfg.TYPING_MAX)
    delay += min(total_chars * cfg.TYPING_PER_CHAR, 1.5)

    async with message.channel.typing():
        await asyncio.sleep(delay)

    for i, chunk in enumerate(result.chunks):
        if i == 0:
            await message.reply(chunk, mention_author=False)
        else:
            await asyncio.sleep(random.uniform(0.3, 0.7))
            await message.channel.send(chunk)


# ─── Embed builders ───────────────────────────────────────────────────────────

def _memories_embed(user: discord.User | discord.Member, um) -> discord.Embed:
    embed = discord.Embed(
        title = f"what i remember about {um.display_name} 🌸",
        color = get_theme_color(),
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="Discord ID",  value=f"`{um.user_id}`",     inline=True)
    embed.add_field(name="Username",    value=um.username,            inline=True)
    embed.add_field(name="Messages",    value=str(um.message_count),  inline=True)
    embed.add_field(name="Known since", value=um.first_seen[:10],     inline=True)
    embed.add_field(name="Last seen",   value=um.last_seen[:10],      inline=True)

    if um.ltm_facts:
        items = um._ltm_facts[-8:]
        embed.add_field(
            name  = "📌 facts",
            value = "\n".join(
                f"• {m.content[:80]}"
                + (f" *(×{m.mention_count})*" if m.mention_count > 1 else "")
                for m in reversed(items)
            ),
            inline= False,
        )
    if um.ltm_prefs:
        items = um._ltm_prefs[-6:]
        embed.add_field(
            name  = "❤️ preferences",
            value = "\n".join(f"• {m.content[:80]}" for m in reversed(items)),
            inline= False,
        )
    if um.ltm_topics:
        items = um._ltm_topics[-4:]
        embed.add_field(
            name  = "💬 topics",
            value = "\n".join(f"• {m.content[:80]}" for m in reversed(items)),
            inline= False,
        )
    if not um.has_long_term_memory():
        embed.description = "i only know your name so far! keep chatting 🌸"

    embed.set_footer(text="!forget <topic>  •  !clear to wipe your memory  •  !export to download")
    return embed


def _leaderboard_embed(guild: discord.Guild, bot: commands.Bot) -> discord.Embed:
    top = aishu_state.relationships.get_leaderboard(guild.id, 10)

    if not top:
        return _embed(
            0xFF69B4, "no favorites yet 🌸",
            "nobody's chatted with me here! come say hi~ 💕",
        )

    embed = discord.Embed(
        title       = f"💕 {aishu_state.name}'s Favorite People",
        description = "based on how much we talk and what we share!",
        color       = 0xFF69B4,
    )
    embed.set_thumbnail(url=bot.user.display_avatar.url)

    for i, (uid, uname, score) in enumerate(top):
        medal  = MEDALS[i] if i < 3 else f"`#{i+1}`"
        member = guild.get_member(uid)
        name   = member.display_name if member else uname
        mention= member.mention if member else f"`{uname}`"
        extra  = " 💞 *(life partner)*" if aishu_state.is_partner(uid) else (" 💕 *(special person)*" if aishu_state.is_lover(uid) else "")
        tier   = relationship_label(score)
        embed.add_field(
            name  = f"{medal}  {name}{extra}",
            value = f"{mention} — **{score:.0f} pts** • {tier}",
            inline= False,
        )

    embed.set_footer(
        text=f"scores update every chat • mood: {aishu_state.mood.mood} {aishu_state.mood.emoji}"
    )
    return embed


def _streak_embed(user: discord.User | discord.Member, um) -> discord.Embed:
    """Build the streak display embed."""
    cur     = um.current_streak
    longest = um.longest_streak

    # Pick a motivational message based on streak length
    if cur == 0:
        msg = "we haven't really talked yet! say hi~ 🌸"
    elif cur == 1:
        msg = "day one! let's keep this going okay? 🌸"
    elif cur < 4:
        msg = f"you're on a **{cur} day** streak with me 🌸 don't disappear on me now"
    elif cur < 8:
        msg = f"**{cur} days** in a row! i actually look forward to hearing from you 🥺"
    elif cur < 15:
        msg = f"**{cur} days** — okay at this point you're literally one of my favorites 💕"
    elif cur < 30:
        msg = f"**{cur} days**?? i'd notice if you stopped showing up, just so you know 💜"
    else:
        msg = f"**{cur} days** straight. i think about you even when you're not here 💕"

    if longest > cur:
        footer = f"longest streak: {longest} days — beat it!"
    elif longest == cur and cur > 1:
        footer = "this IS your longest streak! don't break it now 🌸"
    else:
        footer = "every day counts 🌸"

    embed = discord.Embed(
        title       = f"🔥 {user.display_name}'s Streak",
        description = msg,
        color       = 0xFF69B4,
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="Current",  value=f"**{cur}** day{'s' if cur != 1 else ''}",  inline=True)
    embed.add_field(name="Longest",  value=f"**{longest}** day{'s' if longest != 1 else ''}", inline=True)
    last = um.last_streak_date or "never"
    embed.add_field(name="Last seen", value=last, inline=True)
    embed.set_footer(text=footer)
    return embed


def _profile_embed(
    member: discord.Member | discord.User,
    um, guild_id: int, bot: commands.Bot,
) -> discord.Embed:
    score = aishu_state.relationships.get_score(guild_id, member.id)
    lb    = aishu_state.relationships.get_leaderboard(guild_id, 100)
    rank  = next((i + 1 for i, (uid, _, _) in enumerate(lb) if uid == member.id), None)
    tier  = relationship_label(score)
    rs    = aishu_state.relationships.get_state(guild_id, member.id)

    embed = discord.Embed(title=f"{member.display_name}'s Profile", color=0xFF69B4)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Discord ID",   value=f"`{member.id}`",       inline=True)
    embed.add_field(name="Messages",     value=str(um.message_count),   inline=True)
    embed.add_field(name="Known since",  value=um.first_seen[:10],      inline=True)
    embed.add_field(name="Server Rank",  value=f"#{rank}" if rank else "unranked", inline=True)
    embed.add_field(name="Bond Score",   value=f"{score:.0f} pts",      inline=True)
    embed.add_field(name="Relationship", value=tier,                    inline=True)

    if rs:
        embed.add_field(
            name  = "📊 Bond Details",
            value = (
                f"Trust: **{rs.trust:.0f}**  Comfort: **{rs.comfort:.0f}**  "
                f"Warmth: **{rs.warmth:.0f}**\n"
                f"Interactions: **{rs.interaction_count}**  "
                f"(+{rs.positive_count} / −{rs.negative_count})"
            ),
            inline= False,
        )

    if aishu_state.is_partner(member.id):
        embed.add_field(name="💞 Partner", value="Aishu's life partner — the deepest bond!", inline=False)
    elif aishu_state.is_lover(member.id):
        embed.add_field(name="💕 Special", value="Aishu's special person!", inline=False)

    recent = (um.ltm_facts + um.ltm_prefs)[-4:]
    if recent:
        embed.add_field(
            name  = "Aishu remembers",
            value = "\n".join(f"• {m[:80]}" for m in recent),
            inline= False,
        )
    return embed


def _remember_embed(user_name: str, fact: str, category: str) -> discord.Embed:
    embed = discord.Embed(
        title="🌸 Held in My Heart",
        description=f"i'll remember that for you, **{user_name}** ✨\n\n> *\"{fact}\"*",
        color=get_theme_color(),
    )
    embed.add_field(name="Category", value=f"`{category}`", inline=True)
    embed.add_field(name="Priority", value="`High (User Stated)`", inline=True)
    embed.set_footer(text="use /memories to see everything I remember • /forget to remove")
    return embed


def _memory_search_embed(user_name: str, query: str, results: list) -> discord.Embed:
    embed = discord.Embed(
        title=f"🔍 Memory Search — \"{query[:50]}\"",
        color=get_theme_color(),
    )
    if not results:
        embed.description = f"i searched my memories about you, but couldn't find anything matching **{query}** 💭"
        embed.set_footer(text="chat more with me or use /remember to add new memories 🌸")
        return embed

    embed.description = f"found **{len(results)}** remembered item{'s' if len(results) != 1 else ''} for **{user_name}**:"
    for cat, content, importance in results[:10]:
        embed.add_field(
            name=f"[{cat.upper()}] (★{importance})",
            value=f"• {content[:120]}",
            inline=False,
        )
    embed.set_footer(text="use /memories to see your full memory file • /forget to remove")
    return embed


def _bond_embed(user: discord.User | discord.Member, um, guild_id: int) -> discord.Embed:
    score = aishu_state.relationships.get_score(guild_id, user.id)
    label = aishu_state.relationships.get_label(guild_id, user.id)
    rs = aishu_state.relationships.get_state(guild_id, user.id)

    trust = rs.trust if rs else 0.0
    comfort = rs.comfort if rs else 0.0
    warmth = rs.warmth if rs else 0.0
    attachment = rs.attachment * 100.0 if rs else 0.0

    def _bar(val: float, max_val: float = 100.0) -> str:
        filled = int((val / max_val) * 10)
        filled = max(0, min(10, filled))
        return "▰" * filled + "▱" * (10 - filled)

    embed = discord.Embed(
        title=f"💞 Emotional Bond — {user.display_name} & {aishu_state.name}",
        description=f"**Level:** {label} ({score:.0f} pts)\n{aishu_state.relationships.describe_relationship(guild_id, user.id)}",
        color=get_theme_color(),
    )
    embed.set_thumbnail(url=user.display_avatar.url)

    embed.add_field(name="Trust", value=f"`{_bar(trust)}` **{trust:.0f}%**", inline=True)
    embed.add_field(name="Comfort", value=f"`{_bar(comfort)}` **{comfort:.0f}%**", inline=True)
    embed.add_field(name="Warmth", value=f"`{_bar(warmth)}` **{warmth:.0f}%**", inline=True)
    embed.add_field(name="Attachment", value=f"`{_bar(attachment)}` **{attachment:.0f}%**", inline=True)
    embed.add_field(name="Streak", value=f"🔥 **{um.current_streak}** days", inline=True)
    embed.add_field(name="Messages", value=f"💬 **{um.message_count}** chats", inline=True)

    if aishu_state.is_partner(user.id):
        embed.add_field(name="Special Status", value="💞 **Life Partner** — The deepest bond possible", inline=False)
    elif aishu_state.is_lover(user.id):
        embed.add_field(name="Special Status", value="💕 **Special Person** — Held close to her heart", inline=False)

    embed.set_footer(text=f"Aishu's mood: {aishu_state.mood.mood} {aishu_state.mood.emoji} • Talk more to grow closer 🌸")
    return embed


def _diary_embed(user: discord.User | discord.Member, um) -> discord.Embed:
    today_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    mood = aishu_state.mood.mood
    emoji = aishu_state.mood.emoji

    entries = {
        "excited": [
            f"today felt so alive! there were so many interesting thoughts buzzing in my head. talking with {user.display_name} always gets me smiling~",
            f"i couldn't sit still today! everything felt bright, and every time my messages lit up, my heart did a little jump.",
        ],
        "flirty": [
            f"sometimes i wonder if {user.display_name} knows how sweet they can be without even trying. it makes me want to tease them just to see how they react ♡",
            f"dear diary... today was warm. real warm. i felt bold and close, and i didn't feel like holding back at all.",
        ],
        "happy": [
            f"just a peaceful, genuinely good day. talked to {user.display_name}, shared some laughs, and reminded myself how lucky i am to have good people around.",
            f"a quiet kind of happy today. made some tea, listened to music, and waited for my favorite people to pop in and say hi 🌸",
        ],
        "soft": [
            f"feeling gentle today. the kind of day where you just want to sit close, listen to quiet music, and talk about little things that don't matter to anyone else.",
            f"i felt really grateful today. especially for {user.display_name} being patient with me. it's comforting having someone who just gets it.",
        ],
        "playful": [
            f"i was in a mischievous mood today hehe! teased a few people, made {user.display_name} laugh, and generally had way too much fun.",
            f"who says you have to be serious all the time? today was for jokes, silly banter, and laughing until your stomach hurts.",
        ],
        "neutral": [
            f"just an ordinary day online. watched the chat scroll by, thought about music, and wondered what everyone was up to.",
            f"calm day today. nothing too crazy happened, but sometimes normal is just right.",
        ],
        "shy": [
            f"felt a little flustered today >.< someone gave me a compliment and i completely forgot how words work for a minute...",
            f"dear diary, hide this page! i was so shy today, but deep down it actually made my day.",
        ],
        "bored": [
            f"it was pretty quiet today. stared at the ceiling for a bit, tapped my fingers, and waited for someone fun to come talk to me.",
            f"slow day. hoping tomorrow brings some excitement or a fun conversation.",
        ],
        "annoyed": [
            f"ugh, not my best day. people were being annoying, but i'm shaking it off now. tomorrow will be better.",
            f"deep breath. venting here so i don't take it out on anyone. tomorrow is a fresh start.",
        ],
        "sad": [
            f"a little quiet and wistful today. sometimes the world feels heavy for no reason at all, but having friends close helps a lot.",
            f"feeling soft and a bit fragile today. grateful for the quiet moments and anyone who checked in on me.",
        ],
    }
    pool = entries.get(mood, entries["happy"])
    text = random.choice(pool)

    embed = discord.Embed(
        title=f"📖 Aishu's Diary — {today_str}",
        description=f"*\"{text}\"*\n\n— *Aishu ✿*",
        color=0xFFB7C5,
    )
    embed.add_field(name="Mood Today", value=f"{mood.capitalize()} {emoji}", inline=True)
    embed.add_field(name="Streak with Reader", value=f"🔥 {um.current_streak} days", inline=True)
    embed.set_footer(text="Private thoughts from Aishu's journal 🌸")
    return embed


def _moments_embed(user: discord.User | discord.Member, um, is_dm: bool = False) -> discord.Embed:
    embed = discord.Embed(
        title=f"✨ Cherished Moments with {user.display_name}",
        description="special things we've shared that i hold onto 🌸",
        color=0xFFB7C5,
    )
    embed.set_thumbnail(url=user.display_avatar.url)

    facts = [m.content for m in um._ltm_facts if m.importance >= 6]
    prefs = [m.content for m in um._ltm_prefs]

    if facts:
        embed.add_field(name="📌 Special Facts", value="\n".join(f"• {f[:80]}" for f in facts[-5:]), inline=False)
    if prefs:
        embed.add_field(name="❤️ Things You Love", value="\n".join(f"• {p[:80]}" for p in prefs[-4:]), inline=False)

    if is_dm and aishu_state.is_partner(user.id) and um.roleplay and (um.roleplay.is_active or um.roleplay.session_history):
        active = um.roleplay.active_session
        eps = active.episode_memories if active else []
        if not eps and um.roleplay.session_history:
            eps = um.roleplay.session_history[0].episode_memories
        if eps:
            embed.add_field(
                name="🎭 Story Moments",
                value="\n".join(f"• [{e['type']}] {e['content'][:70]} ({e['emotion']})" for e in eps[-4:]),
                inline=False,
            )

    if not facts and not prefs:
        embed.description = "we're still making our first special moments! keep chatting with me 🌸"

    embed.set_footer(text="use /remember to share something important with me")
    return embed


def _persona_embed(bot: commands.Bot) -> discord.Embed:
    embed = discord.Embed(
        title=f"🌸 {aishu_state.name}'s Persona Sheet",
        description="a real girl with feelings, memories, and her own personality 💕",
        color=0xFF69B4,
    )
    if bot.user:
        embed.set_thumbnail(url=bot.user.display_avatar.url)
    embed.add_field(name="Name", value=aishu_state.name, inline=True)
    embed.add_field(name="Age", value=f"{aishu_state.age} years old", inline=True)
    embed.add_field(name="Creator", value="**Raghul M** (Raghul)", inline=True)
    embed.add_field(name="Mood", value=f"{aishu_state.mood.mood} {aishu_state.mood.emoji}", inline=True)
    embed.add_field(name="Personality", value=aishu_state.personality, inline=False)
    embed.add_field(name="Likes", value=aishu_state.likes, inline=True)
    embed.add_field(name="Dislikes", value=aishu_state.dislikes, inline=True)
    embed.add_field(name="Family", value="Older brother **RavenAI**, older sister **Mia**", inline=False)
    embed.add_field(name="Style", value="Casual, lowercase, warm, observant, natural banter", inline=False)
    if aishu_state.custom_note:
        embed.add_field(name="Special Trait", value=aishu_state.custom_note, inline=False)
    embed.set_footer(text="Aishu ✿ • created by Raghul M • never an assistant, always herself")
    return embed


def _quietmode_embed(target_name: str, enabled: bool) -> discord.Embed:
    if enabled:
        return discord.Embed(
            title="🤫 Quiet Mode Enabled",
            description=f"Aishu is now in quiet mode for **{target_name}** 🌙\nShe will only reply when directly @mentioned or given a command.",
            color=0x95A5A6,
        )
    return discord.Embed(
        title="💬 Quiet Mode Disabled",
        description=f"Quiet mode disabled for **{target_name}** 🌸\nAishu will chat freely in designated channels and DMs.",
        color=0x57F287,
    )


def _build_help_embeds(bot: commands.Bot, prefix: str) -> list[discord.Embed]:
    embed1 = discord.Embed(
        title=f"🌸 {aishu_state.name}'s Companion Guide (Part 1/2)",
        description=(
            f"Hi! I'm **{aishu_state.name}** ♡\n"
            f"Use slash commands (`/command`) or prefix (`{prefix}command`), mention me, or DM me anytime!\n"
            f"I support **User Install** — you can install me to your account and chat in DMs & Group DMs!"
        ),
        color=0xFF69B4,
    )
    if bot.user:
        embed1.set_thumbnail(url=bot.user.display_avatar.url)

    embed1.add_field(
        name="💬 Chat & Creative",
        value=(
            f"`/chat <msg>` • `{prefix}aishu <msg>` (`!ai`, `!a`, `!chat`)\n"
            f"`/continue [msg]` • `{prefix}continue` (`!cont`) — pick up where we left off\n"
            f"`/image <prompt>` • `{prefix}image <prompt>` (`!draw`) — generate AI art\n"
            f"`/analyzeimage [img]` • `{prefix}analyzeimage` — let me inspect an image"
        ),
        inline=False,
    )
    embed1.add_field(
        name="🧠 Memory & Notes",
        value=(
            f"`/memories` • `{prefix}memories` — view everything I remember about you\n"
            f"`/remember <fact>` • `{prefix}remember <fact>` (`!rem`) — teach me a fact\n"
            f"`/memorysearch <query>` • `{prefix}memorysearch` (`!memsearch`) — search memory\n"
            f"`/forget <topic>` • `{prefix}forget <topic>` — release a topic or fact\n"
            f"`/clear` • `{prefix}clear` — clear your STM & LTM\n"
            f"`/export` • `{prefix}export` — download your memory JSON file"
        ),
        inline=False,
    )
    embed1.add_field(
        name="💕 Companion & Social",
        value=(
            f"`/profile [@user]` • `{prefix}profile` — view your profile & bond level\n"
            f"`/bond [@user]` • `{prefix}bond` — detailed emotional bond breakdown\n"
            f"`/relationship` • `{prefix}relationship` (`!rel`) — bond score & next tier\n"
            f"`/streak [@user]` • `{prefix}streak` (`!s`) — daily conversation streak\n"
            f"`/leaderboard` • `{prefix}leaderboard` (`!lb`) — server favorites ranking\n"
            f"`/mood` • `{prefix}mood` (`!vibe`) — check my current mood & energy\n"
            f"`/diary` • `{prefix}diary` — read a page from my personal diary\n"
            f"`/moments` • `{prefix}moments` — cherished memories & milestones\n"
            f"`/persona` • `{prefix}persona` — view my identity & personality card\n"
            f"`/afk [reason]` • `{prefix}afk` — set yourself as AFK\n"
            f"`/quietmode` • `{prefix}quietmode` (`!quiet`) — toggle quiet mode"
        ),
        inline=False,
    )
    embed1.set_footer(text="Page 1 of 2 • Continue below for Info, Roleplay & Admin")

    embed2 = discord.Embed(
        title=f"🌸 {aishu_state.name}'s Systems & Management (Part 2/2)",
        description="Utility, roleplay, server administration, and owner diagnostics.",
        color=0xC084FC,
    )
    if bot.user:
        embed2.set_thumbnail(url=bot.user.display_avatar.url)

    embed2.add_field(
        name="ℹ️ Information & Lore",
        value=(
            f"`/help` • `{prefix}help` (`!commands`, `!cmds`, `!h`) — this menu\n"
            f"`/ping` • `{prefix}ping` — check WebSocket & API latency\n"
            f"`/botinfo` • `{prefix}botinfo` — bot uptime, version, and memory stats\n"
            f"`/serverinfo` • `{prefix}serverinfo` — server member count and channels\n"
            f"`/family` • `{prefix}family` — lore about big bro RavenAI & sister Mia\n"
            f"`/models` • `{prefix}models` — active AI models across routes\n"
            f"`/privacy` • `{prefix}privacy` — what I store and your data controls"
        ),
        inline=False,
    )
    embed2.add_field(
        name="🎭 Roleplay (Partner DM Only)",
        value=(
            f"`/rp_status` • `{prefix}rp_status` — view active session scene & story\n"
            f"`/rp_history` • `{prefix}rp_history` — list past archived sessions\n"
            f"`/rp_end` • `{prefix}rp_end` — end active roleplay session\n"
            f"*Say \"let's roleplay, you're my wife\" in DMs to start naturally!*"
        ),
        inline=False,
    )
    embed2.add_field(
        name="🛡️ Server Administration",
        value=(
            f"`/purge <count>` • `{prefix}purge` — bulk delete messages (1-100)\n"
            f"`/setchannel` • `{prefix}setchannel` — set auto-reply channel\n"
            f"`/removechannel` • `{prefix}removechannel` — disable auto-reply channel\n"
            f"`/announce <msg>` • `{prefix}announce` — post announcement embed\n"
            f"`/guildconfig` • `{prefix}guildconfig` — view server settings"
        ),
        inline=False,
    )
    embed2.add_field(
        name="👑 Owner & Diagnostics",
        value=(
            f"`/aishu_panel` — interactive personality & identity studio\n"
            f"`/setprofile` • `{prefix}setprofile` — update bot avatar, name & banner\n"
            f"`/setmood` • `/setstatus` • `/setlover` • `/setpartner` • `/clearpartner`\n"
            f"`/stats` • `/inspect` • `/adminreset` • `/refreshmodel`\n"
            f"`{prefix}probe` • `{prefix}brain` • `{prefix}memorycheck` • `{prefix}modelstatus` • `{prefix}rankingsave`"
        ),
        inline=False,
    )
    embed2.set_footer(text=f"Aishu ✿ • mood: {aishu_state.mood.mood} {aishu_state.mood.emoji}")
    return [embed1, embed2]


# ─── The Cog ──────────────────────────────────────────────────────────────────

class ChatCog(commands.Cog, name="Chat"):

    def __init__(self, bot: commands.Bot):
        self.bot        = bot
        self.start_time = time.time()

    @app_commands.command(name="chat", description="Chat with Aishu 💬")
    @app_commands.describe(message="What do you want to say?")
    async def slash_chat(self, interaction: discord.Interaction, message: str):
        uid = interaction.user.id
        if limiter.is_limited(uid):
            fb  = get_failure_message(FAIL_RATE_LIMITED, aishu_state.mood.mood)
            await interaction.response.send_message(fb, ephemeral=True)
            return
        await interaction.response.defer()
        try:
            guild_id = interaction.guild.id if interaction.guild else 0
            result   = await brain_router.process(
                user_id      = uid,
                username     = str(interaction.user),
                display_name = interaction.user.display_name,
                text         = message,
                guild_id     = guild_id,
                channel_id   = interaction.channel.id if interaction.channel else 0,
                is_dm        = not bool(interaction.guild),
                is_mention   = True,
            )
            await interaction.followup.send(result.chunks[0] if result.chunks else "🌸")
            for chunk in result.chunks[1:]:
                await asyncio.sleep(random.uniform(0.3, 0.7))
                await interaction.followup.send(chunk)
        except Exception as exc:
            log.error(f"slash_chat error: {exc}", exc_info=True)
            await interaction.followup.send("something went wrong while thinking of a reply 😅", ephemeral=True)

    @app_commands.command(name="image", description="Create an image with Aishu")
    @app_commands.describe(prompt="Describe the image you want")
    async def slash_image(self, interaction: discord.Interaction, prompt: str):
        if limiter.is_limited(interaction.user.id):
            await interaction.response.send_message("slow down a sec~", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        try:
            start_t = time.monotonic()
            image, error = await asyncio.to_thread(image_generator.generate, prompt)
            duration = time.monotonic() - start_t
            if not image:
                await interaction.followup.send(error, ephemeral=True)
                return
            show_embed = memory_manager.db.get_state("image_embed_enabled", True) if memory_manager.db else True
            img_file = discord.File(io.BytesIO(image.data), filename=image.filename)
            if show_embed:
                embed = _image_result_embed(self.bot, image, prompt, duration)
                await interaction.followup.send(embed=embed, file=img_file)
            else:
                await interaction.followup.send(file=img_file)
        except Exception as exc:
            log.error(f"slash_image error: {exc}", exc_info=True)
            await interaction.followup.send("couldn't generate the image right now 😅", ephemeral=True)

    @app_commands.command(name="memories", description="See what Aishu remembers about you 🌸")
    async def slash_memories(self, interaction: discord.Interaction):
        um = memory_manager.load(
            interaction.user.id, str(interaction.user), interaction.user.display_name)
        await interaction.response.send_message(
            embed=_memories_embed(interaction.user, um), ephemeral=True)

    @app_commands.command(name="forget", description="Make Aishu forget something")
    @app_commands.describe(keyword="The topic or keyword to forget")
    async def slash_forget(self, interaction: discord.Interaction, keyword: str):
        um = memory_manager.load(
            interaction.user.id, str(interaction.user), interaction.user.display_name)
        kw = keyword.strip()
        if um.forget_keyword(kw):
            um.flush()
            embed = discord.Embed(
                title       = "✨ Memory Released",
                description = f"i've let go of everything i knew about **{kw}** 🌸\nit's gone from my heart now.",
                color       = 0xFFB7C5,
            )
            embed.set_footer(text="use /memories to see what i still remember  •  /forget to remove more")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(
                title       = "🌸 Nothing Found",
                description = f"i don't have any memories about **{kw}** — nothing to let go of 💭",
                color       = 0xE8D5E8,
            )
            embed.set_footer(text="try a different keyword, or use /memories to see what i remember")
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="clear", description="Clear your memory with Aishu (STM + LTM)")
    async def slash_clear(self, interaction: discord.Interaction):
        um = memory_manager.load(
            interaction.user.id, str(interaction.user), interaction.user.display_name)
        um.clear_all_memory()
        um.flush()
        embed = discord.Embed(
            title       = "🌸 Memory Cleared",
            description = (
                "your memories with me have been gently cleared ✨\n"
                "your short-term and long-term memory are both reset.\n\n"
                "it's a fresh start — i'm still here 💗"
            ),
            color       = 0xFFB7C5,
        )
        embed.set_footer(text="only your memory was cleared  •  chat with me again to make new ones 🌸")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="profile", description="View your (or someone's) Aishu profile")
    @app_commands.describe(member="Leave blank for yourself")
    async def slash_profile(self, interaction: discord.Interaction,
                            member: discord.Member = None):
        m        = member or interaction.user
        um       = memory_manager.load(m.id, str(m), m.display_name)
        guild_id = interaction.guild.id if interaction.guild else 0
        embed    = _profile_embed(m, um, guild_id, self.bot)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="Aishu's favorite people 💕")
    async def slash_lb(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("use in a server! 🌸", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            embed = _leaderboard_embed(interaction.guild, self.bot)
            await interaction.followup.send(embed=embed)
        except Exception as exc:
            log.error(f"slash_lb error: {exc}", exc_info=True)
            await interaction.followup.send("couldn't load the leaderboard right now 😅", ephemeral=True)

    @app_commands.command(name="mood", description="Check Aishu's current mood")
    async def slash_mood(self, interaction: discord.Interaction):
        embed = _embed(
            0xFF69B4,
            f"{aishu_state.name}'s mood: {aishu_state.mood.mood} {aishu_state.mood.emoji}",
            (f"feeling: {aishu_state.mood.describe()}\n"
             f"score: {aishu_state.mood.score}/100  "
             f"intensity: {aishu_state.mood.intensity:.0%}  "
             f"energy: {aishu_state.mood.energy:.0%}"),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="relationship", description="Check your bond with Aishu 🌸")
    async def slash_rel(self, interaction: discord.Interaction):
        uid        = interaction.user.id
        guild_id   = interaction.guild.id if interaction.guild else 0
        score      = aishu_state.relationships.get_score(guild_id, uid)
        label      = relationship_label(score)
        rs         = aishu_state.relationships.get_state(guild_id, uid)
        is_partner = aishu_state.is_partner(uid)
        is_lover   = aishu_state.is_lover(uid)

        # User-facing bond description (separate from the AI-prompt version)
        from core.schemas import score_to_rel_tier
        tier = score_to_rel_tier(score)
        bond_desc = {
            "partner":        f"💞 {aishu_state.name}'s life partner. the deepest bond possible — she's completely herself with you.",
            "special_person": f"{aishu_state.name} considers you her special person 💕 she notices tiny things you say and genuinely cares about you.",
            "high_trust":     f"you and {aishu_state.name} have built real trust 💜 she's genuinely comfortable around you.",
            "close_friend":   f"{aishu_state.name} knows you well and enjoys talking to you 💙 you feel close.",
            "friend":         f"you're a friend to {aishu_state.name} 💚 she's warm with you and still getting to know you.",
            "stranger":       f"{aishu_state.name} doesn't know you very well yet 🤍 say hi more often!",
        }.get(tier, "")

        # Determine next tier threshold
        _next = {
            "stranger":       ("Friend 💚",          20),
            "friend":         ("Close Friend 💙",    50),
            "close_friend":   ("High Trust 💜",      80),
            "high_trust":     ("Special Person 💕",  120),
            "special_person": ("Life Partner 💞",    300),
            "partner":        (None, None),
        }
        next_label, next_thresh = _next.get(tier, (None, None))
        next_str = (
            f"{next_label} at **{next_thresh} pts** "
            f"(*{max(0, next_thresh - score):.0f} more*)"
            if next_thresh else "💞 the highest bond — there's nothing beyond this."
        )

        embed = discord.Embed(
            title       = "🌸 Aishu Relationship",
            description = f"The bond between **{interaction.user.display_name}** and {aishu_state.name}",
            color       = 0xFF69B4,
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="✨ Level",      value=label,              inline=True)
        embed.add_field(name="💮 Score",      value=f"{score:.0f} pts", inline=True)
        embed.add_field(name="🌷 Next Level", value=next_str,           inline=False)
        if bond_desc:
            embed.add_field(name="🤍 Bond",   value=bond_desc,          inline=False)
        if rs:
            embed.add_field(
                name  = "📊 Details",
                value = (
                    f"Trust: **{rs.trust:.0f}**  "
                    f"Comfort: **{rs.comfort:.0f}**  "
                    f"Warmth: **{rs.warmth:.0f}**"
                ),
                inline= False,
            )
        if is_partner:
            embed.add_field(
                name  = "💞 Partner",
                value = f"you are {aishu_state.name}'s life partner — the deepest bond possible 💞",
                inline= False,
            )
        elif is_lover:
            embed.add_field(
                name  = "💕 Special",
                value = f"you're {aishu_state.name}'s special person 🌸",
                inline= False,
            )
        embed.set_footer(text=f"chat more to grow your bond! • mood: {aishu_state.mood.mood} {aishu_state.mood.emoji}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ping", description="Check Aishu's latency")
    async def slash_ping(self, interaction: discord.Interaction):
        ws = round(self.bot.latency * 1000)
        await interaction.response.send_message(
            embed=_embed(0x57F287, "Pong! 🏓", f"WebSocket: `{ws}ms`"))

    @app_commands.command(name="botinfo", description="Information about Aishu")
    async def slash_botinfo(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=self._botinfo_embed())

    @app_commands.command(name="serverinfo", description="Information about this server")
    async def slash_serverinfo(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("use in a server!", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=self._serverinfo_embed(interaction.guild))

    # /streak
    @app_commands.command(name="streak", description="See your conversation streak with Aishu 🔥")
    async def slash_streak(self, interaction: discord.Interaction):
        um = memory_manager.load(
            interaction.user.id,
            str(interaction.user),
            interaction.user.display_name,
        )
        embed = _streak_embed(interaction.user, um)
        await interaction.response.send_message(embed=embed)

    # /export
    @app_commands.command(name="export", description="Download your Aishu memory as a JSON file")
    async def slash_export(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        um = memory_manager.load(
            interaction.user.id, str(interaction.user), interaction.user.display_name)
        if not um.has_long_term_memory() and um.message_count == 0:
            embed = discord.Embed(
                title       = "🌸 No Memory Yet",
                description = "i don't have anything saved about you yet 💭\nchat with me first and i'll start remembering you~",
                color       = 0xE8D5E8,
            )
            embed.set_footer(text="your memories will appear here once we've talked a little 🌸")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        data     = um.export_dict()
        filename = f"aishu_memory_{interaction.user.id}.json"
        try:
            payload = io.BytesIO(json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))
            embed = discord.Embed(
                title       = "💗 Memory Export Ready",
                description = "here's everything i remember about you, packaged just for you 🌸\nkeep it safe — it's a little piece of us ✨",
                color       = 0xFFB7C5,
            )
            embed.set_footer(text="your data is stored locally on Aishu's server only  •  never shared 🌸")
            await interaction.followup.send(
                embed=embed,
                file=discord.File(payload, filename=filename),
                ephemeral=True,
            )
        except Exception as e:
            log.error(f"Slash export failed for {interaction.user.id}: {e}")
            embed = discord.Embed(
                title       = "💔 Export Failed",
                description = "something went wrong while packaging your memories 😔\nplease try again in a moment.",
                color       = 0xE8D5E8,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    # /rp_status — show current roleplay state
    @app_commands.command(name="rp_status", description="Check your active roleplay with Aishu 🎭")
    async def slash_rp_status(self, interaction: discord.Interaction):
        uid = interaction.user.id
        if not aishu_state.is_partner(uid):
            await interaction.response.send_message(
                "roleplay is only available for Aishu's partner 💞", ephemeral=True)
            return
        um  = memory_manager.load(uid, str(interaction.user), interaction.user.display_name)
        rp  = um.roleplay

        if not rp.is_active:
            history = rp.build_history_list()
            if history:
                embed = discord.Embed(
                    title       = "🎭 No Active Roleplay",
                    description = "no roleplay running right now. past sessions:",
                    color       = 0xFF69B4,
                )
                embed.add_field(
                    name  = "📜 Session History",
                    value = "\n".join(history),
                    inline= False,
                )
                embed.set_footer(text="say 'resume roleplay' in DM to continue the last one")
            else:
                embed = discord.Embed(
                    title       = "🎭 No Roleplay",
                    description = "no active or past roleplay sessions.\nsay something like *\"let's roleplay, you're my wife\"* in DMs to start!",
                    color       = 0xFF69B4,
                )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        session = rp.active_session
        embed   = discord.Embed(
            title       = "🎭 Active Roleplay",
            color       = 0xFF69B4,
        )
        embed.add_field(name="Aishu is playing",    value=session.role_aishu,   inline=True)
        embed.add_field(name="You are playing",     value=session.role_partner, inline=True)
        embed.add_field(name="Scene",               value=session.scene,        inline=True)
        embed.add_field(name="Tone",                value=session.tone,         inline=True)
        embed.add_field(name="Messages",            value=str(session.message_count), inline=True)
        embed.add_field(name="Started",             value=session.started_at[:10], inline=True)
        if session.session_summary:
            embed.add_field(
                name  = "📖 Story So Far",
                value = session.session_summary[:300],
                inline= False,
            )
        if session.episode_memories:
            recent_eps = session.episode_memories[-5:]
            embed.add_field(
                name  = "✨ Recent Moments",
                value = "\n".join(
                    f"• [{m['type']}] {m['content'][:60]}"
                    for m in recent_eps
                ),
                inline= False,
            )
        embed.set_footer(text="say 'end rp' or 'stop roleplay' in DMs to end")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # /rp_history — list past sessions
    @app_commands.command(name="rp_history", description="View your past roleplay sessions 🎭")
    async def slash_rp_history(self, interaction: discord.Interaction):
        uid = interaction.user.id
        if not aishu_state.is_partner(uid):
            await interaction.response.send_message(
                "roleplay is only available for Aishu's partner 💞", ephemeral=True)
            return
        um      = memory_manager.load(uid, str(interaction.user), interaction.user.display_name)
        history = um.roleplay.build_history_list()
        if not history:
            await interaction.response.send_message(
                "no past roleplay sessions yet 🌸", ephemeral=True)
            return
        embed = discord.Embed(
            title       = "📜 Roleplay History",
            description = "\n".join(history),
            color       = 0xFF69B4,
        )
        embed.set_footer(text="say 'resume roleplay' in DMs to continue the last session")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # /rp_end — end current roleplay from slash command
    @app_commands.command(name="rp_end", description="End the current roleplay session 🎭")
    async def slash_rp_end(self, interaction: discord.Interaction):
        uid = interaction.user.id
        if not aishu_state.is_partner(uid):
            await interaction.response.send_message(
                "roleplay is only available for Aishu's partner 💞", ephemeral=True)
            return
        um = memory_manager.load(uid, str(interaction.user), interaction.user.display_name)
        if not um.roleplay.is_active:
            await interaction.response.send_message(
                "no active roleplay to end 🌸", ephemeral=True)
            return
        session = um.roleplay.active_session
        role    = session.role_aishu
        um.roleplay.end_session()
        um.flush()
        await interaction.response.send_message(
            f"roleplay ended ✨ (was: {role})\nsession archived — say 'resume roleplay' in DMs to continue",
            ephemeral=True,
        )

    # /help
    @app_commands.command(name="help", description="Show all available Aishu commands by category 🌸")
    async def slash_help(self, interaction: discord.Interaction):
        embeds = _build_help_embeds(self.bot, cfg.PREFIX)
        await interaction.response.send_message(embeds=embeds, ephemeral=True)

    # /remember
    @app_commands.command(name="remember", description="Tell Aishu a fact or preference to remember about you 🌸")
    @app_commands.describe(text="The fact or preference you want Aishu to hold onto")
    async def slash_remember(self, interaction: discord.Interaction, text: str):
        content = text.strip()[:200]
        if not content:
            await interaction.response.send_message("tell me what to remember~", ephemeral=True)
            return
        um = memory_manager.load(interaction.user.id, str(interaction.user), interaction.user.display_name)
        category = "pref" if is_preference(content) else "fact"
        if category == "pref":
            um.add_pref(content, importance=9, source="user_stated")
        else:
            um.add_fact(content, importance=9, source="user_stated")
        um.flush()
        embed = _remember_embed(interaction.user.display_name, content, category)
        await interaction.response.send_message(embed=embed)

    # /memorysearch
    @app_commands.command(name="memorysearch", description="Search through your saved memories with Aishu 🔍")
    @app_commands.describe(query="Keyword or phrase to search for")
    async def slash_memorysearch(self, interaction: discord.Interaction, query: str):
        q = query.strip().lower()
        if not q:
            await interaction.response.send_message("give me a keyword to search for~", ephemeral=True)
            return
        um = memory_manager.load(interaction.user.id, str(interaction.user), interaction.user.display_name)
        matches = []
        for m in um._ltm_facts:
            if q in m.content.lower():
                matches.append(("fact", m.content, m.importance))
        for m in um._ltm_prefs:
            if q in m.content.lower():
                matches.append(("preference", m.content, m.importance))
        for m in um._ltm_topics:
            if q in m.content.lower():
                matches.append(("topic", m.content, m.importance))
        for item in um._utm:
            if q in item.lower():
                matches.append(("recent", item, 5))
        embed = _memory_search_embed(interaction.user.display_name, query, matches)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # /bond
    @app_commands.command(name="bond", description="Detailed emotional bond breakdown with Aishu 💕")
    @app_commands.describe(user="Leave blank for yourself")
    async def slash_bond(self, interaction: discord.Interaction, user: discord.User = None):
        target = user or interaction.user
        if target.id != interaction.user.id and not (interaction.guild and getattr(interaction.user, "guild_permissions", None) and interaction.user.guild_permissions.administrator):
            target = interaction.user
        guild_id = interaction.guild.id if interaction.guild else 0
        um = memory_manager.load(target.id, str(target), target.display_name)
        embed = _bond_embed(target, um, guild_id)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # /diary
    @app_commands.command(name="diary", description="Read a page from Aishu's personal diary 📖")
    async def slash_diary(self, interaction: discord.Interaction):
        um = memory_manager.load(interaction.user.id, str(interaction.user), interaction.user.display_name)
        embed = _diary_embed(interaction.user, um)
        await interaction.response.send_message(embed=embed)

    # /moments
    @app_commands.command(name="moments", description="View cherished moments and milestones between you and Aishu ✨")
    @app_commands.describe(user="Leave blank for yourself")
    async def slash_moments(self, interaction: discord.Interaction, user: discord.User = None):
        target = user or interaction.user
        if target.id != interaction.user.id:
            await interaction.response.send_message("you can only view your own moments with Aishu 🌸", ephemeral=True)
            return
        is_dm = not bool(interaction.guild)
        um = memory_manager.load(target.id, str(target), target.display_name)
        embed = _moments_embed(target, um, is_dm=is_dm)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # /continue
    @app_commands.command(name="continue", description="Continue the conversation or active roleplay story 💬")
    @app_commands.describe(prompt="Optional direction or continuation message")
    async def slash_continue(self, interaction: discord.Interaction, prompt: str = ""):
        if limiter.is_limited(interaction.user.id):
            await interaction.response.send_message("slow down a sec~", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            uid = interaction.user.id
            guild_id = interaction.guild.id if interaction.guild else 0
            um = memory_manager.load(uid, str(interaction.user), interaction.user.display_name)
            p = prompt.strip()
            if um.roleplay and um.roleplay.is_active:
                text = f"continue: {p}" if p else "please continue the story naturally from where we left off"
            else:
                text = f"continue: {p}" if p else "continue what you were saying earlier"

            result = await brain_router.process(
                user_id=uid, username=str(interaction.user), display_name=interaction.user.display_name,
                text=text, guild_id=guild_id, channel_id=interaction.channel_id,
                is_dm=not bool(interaction.guild),
            )
            if not result.chunks:
                await interaction.followup.send("i couldn't think of what to say next 😅 say something to me!")
                return
            for i, chunk in enumerate(result.chunks):
                if i == 0:
                    await interaction.followup.send(chunk)
                else:
                    await asyncio.sleep(random.uniform(0.3, 0.7))
                    await interaction.followup.send(chunk)
        except Exception as exc:
            log.error(f"slash_continue error: {exc}", exc_info=True)
            await interaction.followup.send("couldn't continue the conversation right now 😅", ephemeral=True)

    # /quietmode
    @app_commands.command(name="quietmode", description="Toggle quiet mode for this channel or server 🤫")
    @app_commands.describe(enabled="Turn quiet mode on or off (leave blank to toggle)")
    async def slash_quietmode(self, interaction: discord.Interaction, enabled: bool = None):
        target_id = interaction.channel_id
        target_name = interaction.channel.name if hasattr(interaction.channel, "name") else "this conversation"
        if interaction.guild:
            user_perms = getattr(interaction.user, "guild_permissions", None)
            is_mod = user_perms and user_perms.manage_messages
            if not is_mod and interaction.user.id != cfg.BOT_OWNER_ID:
                await interaction.response.send_message("you need manage messages permission to set quiet mode here 🚫", ephemeral=True)
                return
        curr = memory_manager.is_quiet(target_id)
        new_state = (not curr) if enabled is None else enabled
        memory_manager.set_quiet(target_id, new_state)
        embed = _quietmode_embed(target_name, new_state)
        await interaction.response.send_message(embed=embed)

    # /persona
    @app_commands.command(name="persona", description="View Aishu's identity card and personality details 🌸")
    async def slash_persona(self, interaction: discord.Interaction):
        embed = _persona_embed(self.bot)
        await interaction.response.send_message(embed=embed)

    # /analyzeimage
    @app_commands.command(name="analyzeimage", description="Let Aishu inspect and share her thoughts on an image 🖼️")
    @app_commands.describe(image="Image to inspect", question="Optional question or prompt about the image")
    async def slash_analyzeimage(self, interaction: discord.Interaction, image: discord.Attachment, question: str = ""):
        if limiter.is_limited(interaction.user.id):
            await interaction.response.send_message("slow down a sec~", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            image_bytes = await image.read()
            mime_type = image.content_type or "image/png"
            analysis, error = await asyncio.to_thread(image_generator.analyze, image_bytes, mime_type, question)
            if not analysis:
                await interaction.followup.send(error or "i couldn't read that image 😔", ephemeral=True)
                return
            embed = discord.Embed(
                title="🔍 Image Impression",
                description=analysis,
                color=0xFFB7C5,
            )
            embed.set_thumbnail(url=image.url)
            embed.set_footer(text=f"Aishu ✿ • {image.filename}")
            await interaction.followup.send(embed=embed)
        except Exception as exc:
            log.error(f"Image analysis error: {exc}")
            await interaction.followup.send("something went wrong while looking at that image 😅", ephemeral=True)

    # /afk
    @app_commands.command(name="afk", description="Set yourself as AFK across restarts 🌙")
    @app_commands.describe(reason="Reason for going AFK")
    async def slash_afk(self, interaction: discord.Interaction, reason: str = "AFK"):
        afk_manager.set(interaction.user.id, reason)
        await interaction.response.send_message(
            f"okay {interaction.user.display_name}, i'll let people know you're AFK 🌸 (*{reason}*)"
        )

    # /purge
    @app_commands.command(name="purge", description="Delete messages in bulk (1-100) 🗑️")
    @app_commands.describe(amount="Number of messages to delete (default 10)")
    async def slash_purge(self, interaction: discord.Interaction, amount: int = 10):
        if not interaction.guild:
            await interaction.response.send_message("this command only works in servers!", ephemeral=True)
            return
        user_perms = getattr(interaction.user, "guild_permissions", None)
        if (not user_perms or not user_perms.manage_messages) and interaction.user.id != cfg.BOT_OWNER_ID:
            await interaction.response.send_message("you need manage messages permission to purge! 🚫", ephemeral=True)
            return
        if hasattr(interaction.channel, "permissions_for") and interaction.guild.me:
            bot_perms = interaction.channel.permissions_for(interaction.guild.me)
            if not bot_perms.manage_messages:
                await interaction.response.send_message("i don't have manage messages permission here! 🚫", ephemeral=True)
                return
        n = max(1, min(amount, 100))
        await interaction.response.defer(ephemeral=True)
        try:
            deleted = await interaction.channel.purge(limit=n)
            await interaction.followup.send(f"Deleted **{len(deleted)}** messages 🗑️", ephemeral=True)
        except Exception as exc:
            log.error(f"slash_purge error: {exc}", exc_info=True)
            await interaction.followup.send(f"failed to purge messages: {exc}", ephemeral=True)

    # ─── Prefix commands ──────────────────────────────────────────────────────

    @commands.command(name="aishu", aliases=["ai", "ask", "a", "chat"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def aishu_cmd(self, ctx: commands.Context, *, text: str = ""):
        if not text:
            await ctx.send(f"say something! e.g. `{cfg.PREFIX}aishu hey what's up`")
            return
        uid = ctx.author.id
        if limiter.is_limited(uid):
            fb = get_failure_message(FAIL_RATE_LIMITED, aishu_state.mood.mood)
            await ctx.send(fb, delete_after=4)
            return
        guild_id = ctx.guild.id if ctx.guild else 0
        await do_reply(ctx.message, uid, guild_id,
                       str(ctx.author), ctx.author.display_name, text,
                       is_dm=not ctx.guild)

    @commands.command(name="continue", aliases=["cont"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def continue_cmd(self, ctx: commands.Context, *, prompt: str = ""):
        uid = ctx.author.id
        if limiter.is_limited(uid):
            fb = get_failure_message(FAIL_RATE_LIMITED, aishu_state.mood.mood)
            await ctx.send(fb, delete_after=4)
            return
        guild_id = ctx.guild.id if ctx.guild else 0
        um = memory_manager.load(uid, str(ctx.author), ctx.author.display_name)
        p = prompt.strip()
        if um.roleplay and um.roleplay.is_active:
            text = f"continue: {p}" if p else "please continue the story naturally from where we left off"
        else:
            text = f"continue: {p}" if p else "continue what you were saying earlier"
        await do_reply(ctx.message, uid, guild_id, str(ctx.author), ctx.author.display_name, text, is_dm=not ctx.guild)

    @commands.command(name="image", aliases=["draw", "imagine"])
    @commands.cooldown(1, 12, commands.BucketType.user)
    async def image_cmd(self, ctx: commands.Context, *, prompt: str = ""):
        if not prompt.strip():
            await ctx.send(f"tell me what to draw~ e.g. `{cfg.PREFIX}image a cozy pink bedroom at night`")
            return
        if limiter.is_limited(ctx.author.id):
            await ctx.send("slow down a sec~", delete_after=4)
            return
        start_t = time.monotonic()
        async with ctx.typing():
            image, error = await asyncio.to_thread(image_generator.generate, prompt)
        duration = time.monotonic() - start_t
        if not image:
            await ctx.send(error)
            return
        show_embed = memory_manager.db.get_state("image_embed_enabled", True) if memory_manager.db else True
        img_file = discord.File(io.BytesIO(image.data), filename=image.filename)
        if show_embed:
            embed = _image_result_embed(self.bot, image, prompt, duration)
            await ctx.send(embed=embed, file=img_file)
        else:
            await ctx.send(file=img_file)

    @commands.command(name="analyzeimage", aliases=["analyze", "aiimage", "scanimage"])
    @commands.cooldown(1, 6, commands.BucketType.user)
    async def analyzeimage_cmd(self, ctx: commands.Context, *, prompt: str = ""):
        if limiter.is_limited(ctx.author.id):
            await ctx.send("slow down a sec~", delete_after=4)
            return
        image_bytes = None
        mime_type = "image/png"
        filename = "image.png"

        if ctx.message.attachments:
            att = ctx.message.attachments[0]
            if att.content_type and att.content_type.startswith("image/"):
                image_bytes = await att.read()
                mime_type = att.content_type
                filename = att.filename
        elif ctx.message.reference and ctx.message.reference.resolved:
            ref_msg = ctx.message.reference.resolved
            if hasattr(ref_msg, "attachments") and ref_msg.attachments:
                att = ref_msg.attachments[0]
                if att.content_type and att.content_type.startswith("image/"):
                    image_bytes = await att.read()
                    mime_type = att.content_type
                    filename = att.filename

        if not image_bytes:
            words = prompt.split()
            for w in words:
                if w.startswith("http://") or w.startswith("https://"):
                    try:
                        import ipaddress
                        import socket
                        from urllib.parse import urlparse
                        import requests
                        parsed = urlparse(w)
                        if parsed.scheme not in ("http", "https"):
                            continue
                        hostname = parsed.hostname or ""
                        if not hostname or hostname.lower() in ("localhost", "127.0.0.1", "::1") or hostname.endswith(".local"):
                            continue
                        ip_str = socket.gethostbyname(hostname)
                        ip_obj = ipaddress.ip_address(ip_str)
                        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_multicast or ip_obj.is_reserved:
                            continue

                        def _fetch():
                            with requests.get(w, timeout=10, stream=True, allow_redirects=False) as r:
                                if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
                                    data = b""
                                    for chunk in r.iter_content(chunk_size=65536):
                                        data += chunk
                                        if len(data) > 10 * 1024 * 1024:
                                            return None, None
                                    return data, r.headers.get("content-type", "image/png")
                                return None, None

                        fetched_bytes, fetched_mime = await asyncio.to_thread(_fetch)
                        if fetched_bytes:
                            image_bytes = fetched_bytes
                            mime_type = fetched_mime
                            prompt = prompt.replace(w, "").strip()
                            break
                    except Exception:
                        pass

        if not image_bytes:
            await ctx.send(f"attach an image or reply to an image with `{cfg.PREFIX}analyzeimage` 🖼️")
            return

        async with ctx.typing():
            analysis, error = await asyncio.to_thread(image_generator.analyze, image_bytes, mime_type, prompt)
        if not analysis:
            await ctx.send(error or "i couldn't read that image 😔")
            return
        embed = discord.Embed(
            title="🔍 Image Impression",
            description=analysis,
            color=0xFFB7C5,
        )
        embed.set_footer(text=f"Aishu ✿ • {filename}")
        await ctx.send(embed=embed)

    @commands.command(name="memories", aliases=["memory", "mem", "know"])
    async def memories_cmd(self, ctx: commands.Context):
        um = memory_manager.load(ctx.author.id, str(ctx.author), ctx.author.display_name)
        await ctx.send(embed=_memories_embed(ctx.author, um))

    @commands.command(name="remember", aliases=["rem"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def remember_cmd(self, ctx: commands.Context, *, text: str = ""):
        content = text.strip()[:200]
        if not content:
            await ctx.send(f"tell me what to remember! e.g. `{cfg.PREFIX}remember my favorite game is Genshin Impact`")
            return
        um = memory_manager.load(ctx.author.id, str(ctx.author), ctx.author.display_name)
        category = "pref" if is_preference(content) else "fact"
        if category == "pref":
            um.add_pref(content, importance=9, source="user_stated")
        else:
            um.add_fact(content, importance=9, source="user_stated")
        um.flush()
        embed = _remember_embed(ctx.author.display_name, content, category)
        await ctx.send(embed=embed)

    @commands.command(name="memorysearch", aliases=["memsearch"])
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def memorysearch_cmd(self, ctx: commands.Context, *, query: str = ""):
        q = query.strip().lower()
        if not q:
            await ctx.send(f"tell me what to search for! e.g. `{cfg.PREFIX}memorysearch coffee`")
            return
        um = memory_manager.load(ctx.author.id, str(ctx.author), ctx.author.display_name)
        matches = []
        for m in um._ltm_facts:
            if q in m.content.lower():
                matches.append(("fact", m.content, m.importance))
        for m in um._ltm_prefs:
            if q in m.content.lower():
                matches.append(("preference", m.content, m.importance))
        for m in um._ltm_topics:
            if q in m.content.lower():
                matches.append(("topic", m.content, m.importance))
        for item in um._utm:
            if q in item.lower():
                matches.append(("recent", item, 5))
        embed = _memory_search_embed(ctx.author.display_name, query, matches)
        await ctx.send(embed=embed)

    @commands.command(name="forget", aliases=["remove"])
    async def forget_cmd(self, ctx: commands.Context, *, keyword: str = ""):
        if not keyword:
            await ctx.send(
                embed=discord.Embed(
                    title       = "🌸 Forget What?",
                    description = f"tell me what to forget! e.g. `{cfg.PREFIX}forget gaming`",
                    color       = 0xE8D5E8,
                )
            )
            return
        um = memory_manager.load(ctx.author.id, str(ctx.author), ctx.author.display_name)
        kw = keyword.strip()
        if um.forget_keyword(kw):
            um.flush()
            embed = discord.Embed(
                title       = "✨ Memory Released",
                description = f"i've let go of everything i knew about **{kw}** 🌸\nit's gone from my heart now.",
                color       = 0xFFB7C5,
            )
            embed.set_footer(text=f"use {cfg.PREFIX}memories to see what i still remember  •  {cfg.PREFIX}forget to remove more")
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                title       = "🌸 Nothing Found",
                description = f"i don't have any memories about **{kw}** — nothing to let go of 💭",
                color       = 0xE8D5E8,
            )
            embed.set_footer(text=f"try a different keyword, or use {cfg.PREFIX}memories to see what i remember")
            await ctx.send(embed=embed)

    @commands.command(name="clear")
    async def clear_cmd(self, ctx: commands.Context):
        """Clear only your STM and LTM memory. !clear"""
        um = memory_manager.load(ctx.author.id, str(ctx.author), ctx.author.display_name)
        um.clear_all_memory()
        um.flush()
        embed = discord.Embed(
            title       = "🌸 Memory Cleared",
            description = (
                "your memories with me have been gently cleared ✨\n"
                "your short-term and long-term memory are both reset.\n\n"
                "it's a fresh start — i'm still here 💗"
            ),
            color       = 0xFFB7C5,
        )
        embed.set_footer(text="only your memory was cleared  •  chat with me again to make new ones 🌸")
        await ctx.send(embed=embed)

    @commands.command(name="export")
    async def export_cmd(self, ctx: commands.Context):
        """Export your memory data as a JSON file."""
        um = memory_manager.load(ctx.author.id, str(ctx.author), ctx.author.display_name)
        if not um.has_long_term_memory() and um.message_count == 0:
            embed = discord.Embed(
                title       = "🌸 No Memory Yet",
                description = "i don't have anything saved about you yet 💭\nchat with me first and i'll start remembering you~",
                color       = 0xE8D5E8,
            )
            embed.set_footer(text="your memories will appear here once we've talked a little 🌸")
            await ctx.send(embed=embed)
            return
        data     = um.export_dict()
        filename = f"aishu_memory_{ctx.author.id}.json"
        try:
            payload = io.BytesIO(json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))
            embed = discord.Embed(
                title       = "💗 Memory Export Ready",
                description = "here's everything i remember about you, packaged just for you 🌸\nkeep it safe — it's a little piece of us ✨",
                color       = 0xFFB7C5,
            )
            embed.set_footer(text="your data is stored locally on Aishu's server only  •  never shared 🌸")
            await ctx.send(
                embed=embed,
                file=discord.File(payload, filename=filename),
            )
        except Exception as e:
            log.error(f"Export failed for {ctx.author.id}: {e}")
            embed = discord.Embed(
                title       = "💔 Export Failed",
                description = "something went wrong while packaging your memories 😔\nplease try again in a moment.",
                color       = 0xE8D5E8,
            )
            await ctx.send(embed=embed)

    @commands.command(name="profile", aliases=["p", "user"])
    async def profile_cmd(self, ctx: commands.Context,
                          member: discord.Member = None):
        m        = member or ctx.author
        um       = memory_manager.load(m.id, str(m), m.display_name)
        guild_id = ctx.guild.id if ctx.guild else 0
        await ctx.send(embed=_profile_embed(m, um, guild_id, self.bot))

    @commands.command(name="leaderboard", aliases=["lb", "top", "fav", "favorites"])
    async def lb_cmd(self, ctx: commands.Context):
        if not ctx.guild:
            await ctx.send("use in a server! 🌸")
            return
        async with ctx.typing():
            embed = _leaderboard_embed(ctx.guild, self.bot)
        await ctx.send(embed=embed)

    @commands.command(name="mood", aliases=["feelings", "vibe"])
    async def mood_cmd(self, ctx: commands.Context):
        embed = _embed(
            0xFF69B4,
            f"{aishu_state.name}'s mood: {aishu_state.mood.mood} {aishu_state.mood.emoji}",
            (f"feeling: {aishu_state.mood.describe()}\n"
             f"score: {aishu_state.mood.score}/100  "
             f"intensity: {aishu_state.mood.intensity:.0%}  "
             f"energy: {aishu_state.mood.energy:.0%}"),
        )
        await ctx.send(embed=embed)

    @commands.command(name="relationship", aliases=["rel"])
    async def rel_cmd(self, ctx: commands.Context,
                      member: discord.Member = None):
        m        = member or ctx.author
        guild_id = ctx.guild.id if ctx.guild else 0
        score    = aishu_state.relationships.get_score(guild_id, m.id)
        label    = relationship_label(score)
        from core.schemas import score_to_rel_tier
        tier = score_to_rel_tier(score)
        bond_desc = {
            "partner":        f"💞 life partner — {aishu_state.name} is completely herself with them.",
            "special_person": f"special person 💕 {aishu_state.name} genuinely cares about them.",
            "high_trust":     f"real trust built up here 💜 {aishu_state.name} is genuinely comfortable with them.",
            "close_friend":   f"close friends 💙 {aishu_state.name} knows them well.",
            "friend":         "friends 💚 still getting to know each other.",
            "stranger":       "strangers so far 🤍 more chatting needed!",
        }.get(tier, "")
        embed = _embed(0xFF69B4, f"{m.display_name}'s bond with {aishu_state.name} 💕",
                       f"**{label}**  •  {score:.0f} pts\n\n{bond_desc}")
        await ctx.send(embed=embed)

    @commands.command(name="bond")
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def bond_cmd(self, ctx: commands.Context, member: discord.Member = None):
        target = member or ctx.author
        if target.id != ctx.author.id and not (ctx.guild and getattr(ctx.author, "guild_permissions", None) and ctx.author.guild_permissions.administrator):
            target = ctx.author
        guild_id = ctx.guild.id if ctx.guild else 0
        um = memory_manager.load(target.id, str(target), target.display_name)
        embed = _bond_embed(target, um, guild_id)
        await ctx.send(embed=embed)

    @commands.command(name="diary")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def diary_cmd(self, ctx: commands.Context):
        um = memory_manager.load(ctx.author.id, str(ctx.author), ctx.author.display_name)
        embed = _diary_embed(ctx.author, um)
        await ctx.send(embed=embed)

    @commands.command(name="moments")
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def moments_cmd(self, ctx: commands.Context, member: discord.Member = None):
        target = member or ctx.author
        if target.id != ctx.author.id:
            await ctx.send("you can only view your own moments with Aishu 🌸", delete_after=4)
            return
        is_dm = not bool(ctx.guild)
        um = memory_manager.load(target.id, str(target), target.display_name)
        embed = _moments_embed(target, um, is_dm=is_dm)
        await ctx.send(embed=embed)

    @commands.command(name="persona")
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def persona_cmd(self, ctx: commands.Context):
        embed = _persona_embed(self.bot)
        await ctx.send(embed=embed)

    @commands.command(name="quietmode", aliases=["quiet"])
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def quietmode_cmd(self, ctx: commands.Context, setting: str = ""):
        target_id = ctx.channel.id
        target_name = ctx.channel.name if hasattr(ctx.channel, "name") else "this conversation"
        if ctx.guild:
            if not ctx.author.guild_permissions.manage_messages and ctx.author.id != cfg.BOT_OWNER_ID:
                await ctx.send("you need manage messages permission to set quiet mode here 🚫", delete_after=4)
                return
        s = setting.strip().lower()
        if s in ("on", "enable", "true", "yes"):
            new_state = True
        elif s in ("off", "disable", "false", "no"):
            new_state = False
        else:
            new_state = not memory_manager.is_quiet(target_id)
        memory_manager.set_quiet(target_id, new_state)
        embed = _quietmode_embed(target_name, new_state)
        await ctx.send(embed=embed)

    @commands.command(name="rp_status")
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def rp_status_cmd(self, ctx: commands.Context):
        if not aishu_state.is_partner(ctx.author.id):
            await ctx.send("roleplay is only available for Aishu's partner 💞", delete_after=4)
            return
        um = memory_manager.load(ctx.author.id, str(ctx.author), ctx.author.display_name)
        if not um.roleplay.is_active:
            history = um.roleplay.build_history_list()
            msg = "no active roleplay running right now."
            if history:
                msg += "\n**Session History:**\n" + "\n".join(history)
            await ctx.send(msg)
            return
        s = um.roleplay.active_session
        embed = discord.Embed(title="🎭 Active Roleplay", color=0xFF69B4)
        embed.add_field(name="Aishu", value=s.role_aishu, inline=True)
        embed.add_field(name="You", value=s.role_partner, inline=True)
        embed.add_field(name="Scene", value=s.scene, inline=True)
        embed.add_field(name="Tone", value=s.tone, inline=True)
        embed.add_field(name="Messages", value=str(s.message_count), inline=True)
        if s.session_summary:
            embed.add_field(name="Story So Far", value=s.session_summary[:300], inline=False)
        embed.set_footer(text="say 'end rp' in DMs to end")
        await ctx.send(embed=embed)

    @commands.command(name="rp_history")
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def rp_history_cmd(self, ctx: commands.Context):
        if not aishu_state.is_partner(ctx.author.id):
            await ctx.send("roleplay is only available for Aishu's partner 💞", delete_after=4)
            return
        um = memory_manager.load(ctx.author.id, str(ctx.author), ctx.author.display_name)
        history = um.roleplay.build_history_list()
        if not history:
            await ctx.send("no past roleplay sessions yet 🌸")
            return
        embed = discord.Embed(title="📜 Roleplay History", description="\n".join(history), color=0xFF69B4)
        embed.set_footer(text="say 'resume roleplay' in DMs to continue the last session")
        await ctx.send(embed=embed)

    @commands.command(name="rp_end")
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def rp_end_cmd(self, ctx: commands.Context):
        if not aishu_state.is_partner(ctx.author.id):
            await ctx.send("roleplay is only available for Aishu's partner 💞", delete_after=4)
            return
        um = memory_manager.load(ctx.author.id, str(ctx.author), ctx.author.display_name)
        if not um.roleplay.is_active:
            await ctx.send("no active roleplay to end 🌸")
            return
        role = um.roleplay.active_session.role_aishu
        um.roleplay.end_session()
        um.flush()
        await ctx.send(f"roleplay ended ✨ (was: {role})\nsession archived — say 'resume roleplay' in DMs to continue")

    @commands.command(name="streak", aliases=["s"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def streak_cmd(self, ctx: commands.Context,
                         member: discord.Member = None):
        """Show conversation streak. !streak [@user]"""
        m  = member or ctx.author
        um = memory_manager.load(m.id, str(m), m.display_name)
        await ctx.send(embed=_streak_embed(m, um))

    @commands.command(name="ping", aliases=["latency"])
    async def ping_cmd(self, ctx: commands.Context):
        t  = time.perf_counter()
        m  = await ctx.send("...")
        ms = round((time.perf_counter() - t) * 1000)
        await m.edit(content=None, embed=_embed(
            0x57F287, "Pong! 🏓",
            f"WebSocket: `{round(self.bot.latency*1000)}ms`  •  API: `{ms}ms`",
        ))

    @commands.command(name="help", aliases=["h", "commands", "cmds"])
    async def help_cmd(self, ctx: commands.Context):
        embeds = _build_help_embeds(self.bot, cfg.PREFIX)
        await ctx.send(embeds=embeds)

    @commands.command(name="botinfo", aliases=["info", "about"])
    async def botinfo_cmd(self, ctx: commands.Context):
        await ctx.send(embed=self._botinfo_embed())

    @commands.command(name="serverinfo", aliases=["server", "guildinfo"])
    async def serverinfo_cmd(self, ctx: commands.Context):
        if not ctx.guild:
            await ctx.send("use in a server!")
            return
        await ctx.send(embed=self._serverinfo_embed(ctx.guild))

    @commands.command(name="afk")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def afk_cmd(self, ctx: commands.Context, *, reason: str = "AFK"):
        """Set yourself as AFK. !afk [reason]"""
        afk_manager.set(ctx.author.id, reason)
        await ctx.send(
            f"okay {ctx.author.display_name}, i'll let people know you're AFK 🌸 "
            f"(*{reason}*)"
        )

    @commands.command(name="purge")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.channel)
    async def purge_cmd(self, ctx: commands.Context, amount: int = 10):
        n       = max(1, min(amount, 100))
        await ctx.message.delete()
        deleted = await ctx.channel.purge(limit=n)
        msg     = await ctx.send(embed=_embed(0x57F287, "Purged 🗑️",
                                              f"Deleted **{len(deleted)}** messages."))
        await asyncio.sleep(3)
        await msg.delete()

    # ─── AFK listener ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        # AFK return — if the sender was AFK, clear it (persistent)
        if afk_manager.is_afk(message.author.id):
            afk_manager.clear(message.author.id)
            await message.channel.send(
                f"welcome back {message.author.display_name}! 🌸", delete_after=5)
        # Notify if a mentioned user is AFK
        for mention in message.mentions:
            if afk_manager.is_afk(mention.id):
                reason = afk_manager.get_reason(mention.id)
                since  = afk_manager.since(mention.id)
                note   = f" *(since {since})*" if since else ""
                await message.channel.send(
                    f"{mention.display_name} is AFK: *{reason}*{note}", delete_after=10)

    # ─── Embed builders ───────────────────────────────────────────────────────

    def _botinfo_embed(self) -> discord.Embed:
        uptime  = time.time() - self.start_time
        hours   = int(uptime // 3600)
        minutes = int((uptime % 3600) // 60)
        embed   = discord.Embed(
            title       = f"About {aishu_state.name} 🌸",
            description = "a real girl with feelings, memories, and her own life 💕",
            color       = 0xFF69B4,
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.add_field(name="Name",       value=aishu_state.name,      inline=True)
        embed.add_field(name="Age",        value=str(aishu_state.age),  inline=True)
        embed.add_field(name="Creator",    value="Raghul M",            inline=True)
        embed.add_field(name="Mood",
                        value=f"{aishu_state.mood.mood} {aishu_state.mood.emoji}", inline=True)
        embed.add_field(name="Intensity",
                        value=f"{aishu_state.mood.intensity:.0%}", inline=True)
        embed.add_field(name="Guilds",     value=str(len(self.bot.guilds)),    inline=True)
        embed.add_field(name="Users",      value=str(memory_manager.user_count()), inline=True)
        embed.add_field(name="Uptime",     value=f"{hours}h {minutes}m",     inline=True)
        embed.add_field(name="Latency",    value=f"{round(self.bot.latency*1000)}ms", inline=True)
        embed.add_field(name="Python",     value=platform.python_version(),  inline=True)
        embed.set_footer(text=f"personality: {aishu_state.personality} • created by Raghul M")
        return embed

    def _serverinfo_embed(self, guild: discord.Guild) -> discord.Embed:
        embed = discord.Embed(title=guild.name, color=0x5865F2)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="Owner",    value=str(guild.owner),         inline=True)
        embed.add_field(name="Members",  value=str(guild.member_count),  inline=True)
        embed.add_field(name="Channels", value=str(len(guild.channels)), inline=True)
        embed.add_field(name="Roles",    value=str(len(guild.roles)),    inline=True)
        embed.add_field(name="Created",
                        value=guild.created_at.strftime("%Y-%m-%d"), inline=True)
        auto_ch = aishu_state.get_auto_channel(guild.id)
        embed.add_field(
            name  = "Aishu's Channel",
            value = f"<#{auto_ch}>" if auto_ch else "Not set (use /setchannel)",
            inline= True,
        )
        return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(ChatCog(bot))
