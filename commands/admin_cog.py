"""
commands/admin_cog.py — Admin, Owner, and Developer commands.

Admin:     /setchannel, /removechannel, /announce, /guildconfig
Owner:     /aishu_panel, /setmood, /setstatus, /setlover, /setpartner, /clearpartner,
           /stats, /inspect, /adminreset
Public:    /family, /models, /privacy
Developer: !probe, !brain, !memorycheck, !modelstatus, !rankingsave
"""

import asyncio
from datetime import datetime, timezone
import json

import discord
from discord import app_commands
from discord.ext import commands

import config.settings as cfg
from brain.model_controller import model_controller
from brain.router import brain_router
from core.memory.memory_manager import memory_manager
from core.personality.aishu_state import aishu_state
from core.relationship.relationship_system import RelationshipSystem
from core.mood.mood_system import MOOD_THRESHOLDS, MOOD_FLOOR
from utilities.helpers import mood_to_emoji
from utilities.logger import get_logger

log = get_logger("commands.admin")

ALL_MOODS  = [label for _, label in MOOD_THRESHOLDS] + [MOOD_FLOOR]
MOOD_EMOJIS = {m: mood_to_emoji(m) for m in ALL_MOODS}


def _embed(color: int, title: str, desc: str = "") -> discord.Embed:
    return discord.Embed(title=title, description=desc, color=color)


def _owner_only(interaction: discord.Interaction) -> bool:
    return interaction.user.id == cfg.BOT_OWNER_ID


# ─── Settings Panel UI ────────────────────────────────────────────────────────

class SettingsModal(discord.ui.Modal):
    def __init__(self, field: str, label: str, current: str,
                 placeholder: str = "", max_len: int = 200):
        super().__init__(title=f"Edit: {field}")
        self.field = field
        self.input = discord.ui.TextInput(
            label=label, default=str(current), placeholder=placeholder,
            max_length=max_len,
            style=discord.TextStyle.paragraph if max_len > 100 else discord.TextStyle.short,
        )
        self.add_item(self.input)

    async def on_submit(self, interaction: discord.Interaction):
        val = self.input.value.strip()
        if self.field == "age":
            try:
                val = int(val)
            except ValueError:
                await interaction.response.send_message("❌ Age must be a number.", ephemeral=True)
                return
        aishu_state.set(self.field, val, force_save=True)
        if self.field == "status_text":
            await interaction.client.change_presence(activity=discord.Game(name=val))
        await interaction.response.send_message(
            f"✅ **{self.field}** updated to: `{val}`", ephemeral=True)


class MoodDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=m.capitalize(), value=m,
                emoji=MOOD_EMOJIS.get(m, "🌸"),
                default=(m == aishu_state.mood.mood),
            )
            for m in ALL_MOODS
        ]
        super().__init__(placeholder="Set Aishu's mood...", options=options)

    async def callback(self, interaction: discord.Interaction):
        mood = self.values[0]
        aishu_state.mood.force_mood(mood)
        aishu_state.save(force=True)
        await interaction.response.send_message(
            f"Mood set to **{mood}** {MOOD_EMOJIS.get(mood, '🌸')}", ephemeral=True)


class StabilityDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Low (0.3) — moody", value="0.3"),
            discord.SelectOption(label="Normal (0.7) — balanced", value="0.7"),
            discord.SelectOption(label="High (0.9) — very stable", value="0.9"),
        ]
        super().__init__(placeholder="Set mood stability...", options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        val = float(self.values[0])
        aishu_state.mood.set_stability(val)
        aishu_state.save(force=True)
        await interaction.response.send_message(
            f"Mood stability set to **{val}**", ephemeral=True)


class LoverModal(discord.ui.Modal, title="Set Aishu's Special Person"):
    def __init__(self):
        super().__init__()
        self.user_id_field = discord.ui.TextInput(
            label="Discord User ID",
            placeholder="Right-click user → Copy ID (Developer Mode required)",
            max_length=25,
        )
        self.name_field = discord.ui.TextInput(
            label="Their name/nickname",
            placeholder="e.g. Arjun",
            max_length=50,
        )
        self.add_item(self.user_id_field)
        self.add_item(self.name_field)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            uid = int(self.user_id_field.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
            return
        name = self.name_field.value.strip()
        aishu_state.set_lover(uid, name)
        await interaction.response.send_message(
            f"💕 Aishu's special person set to **{name}** (ID: `{uid}`)", ephemeral=True)


class BotUsernameModal(discord.ui.Modal, title="Update Aishu's Discord Name"):
    def __init__(self):
        super().__init__()
        self.name_input = discord.ui.TextInput(
            label="Discord bot username", default=aishu_state.name,
            min_length=2, max_length=32,
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        name = self.name_input.value.strip()
        try:
            await interaction.client.user.edit(username=name)
        except discord.HTTPException as exc:
            await interaction.response.send_message(
                f"Discord could not update Aishu's username right now: {exc.text or 'try again later.'}",
                ephemeral=True,
            )
            return
        aishu_state.set("name", name, force_save=True)
        await interaction.response.send_message(
            f"✨ Aishu is now **{name}** on Discord and in her profile.", ephemeral=True,
        )


class SettingsPanelView(discord.ui.View):
    def __init__(self, guild):
        super().__init__(timeout=180)
        self.guild = guild
        self.add_item(MoodDropdown())
        self.add_item(StabilityDropdown())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == cfg.BOT_OWNER_ID:
            return True
        await interaction.response.send_message("❌ only the bot owner can change these settings.", ephemeral=True)
        return False

    @discord.ui.button(label="✏️ Name",        style=discord.ButtonStyle.secondary, row=2)
    async def edit_name(self, i, _):
        await i.response.send_modal(SettingsModal("name", "Name", aishu_state.name, max_len=30))

    @discord.ui.button(label="🎂 Age",         style=discord.ButtonStyle.secondary, row=2)
    async def edit_age(self, i, _):
        await i.response.send_modal(SettingsModal("age", "Age (number)", str(aishu_state.age),
                                                  "e.g. 17", max_len=3))

    @discord.ui.button(label="✨ Personality", style=discord.ButtonStyle.secondary, row=2)
    async def edit_personality(self, i, _):
        await i.response.send_modal(SettingsModal("personality", "Personality Traits",
                                                  aishu_state.personality, max_len=200))

    @discord.ui.button(label="❤️ Likes",       style=discord.ButtonStyle.secondary, row=3)
    async def edit_likes(self, i, _):
        await i.response.send_modal(SettingsModal("likes", "Likes", aishu_state.likes, max_len=200))

    @discord.ui.button(label="💔 Dislikes",    style=discord.ButtonStyle.secondary, row=3)
    async def edit_dislikes(self, i, _):
        await i.response.send_modal(SettingsModal("dislikes", "Dislikes",
                                                  aishu_state.dislikes, max_len=200))

    @discord.ui.button(label="💌 Set Lover",   style=discord.ButtonStyle.danger,    row=3)
    async def set_lover(self, i, _):
        await i.response.send_modal(LoverModal())

    @discord.ui.button(label="📝 Custom Note", style=discord.ButtonStyle.secondary, row=4)
    async def edit_custom(self, i, _):
        await i.response.send_modal(SettingsModal("custom_note", "Extra Note",
                                                  aishu_state.custom_note, max_len=300))

    @discord.ui.button(label="📢 Status",      style=discord.ButtonStyle.secondary, row=4)
    async def edit_status(self, i, _):
        await i.response.send_modal(SettingsModal("status_text", "Status Text",
                                                  aishu_state.status_text, max_len=60))

    @discord.ui.button(label="💜 Clear Lover", style=discord.ButtonStyle.danger,    row=4)
    async def clear_lover(self, i, _):
        aishu_state.clear_lover()
        await i.response.send_message("Lover cleared 💔", ephemeral=True)

    @discord.ui.button(label="🔄 Refresh",     style=discord.ButtonStyle.primary,   row=4)
    async def refresh(self, i, _):
        await i.response.edit_message(embed=_panel_embed(self.guild), view=self)


class ProfileSettingsView(SettingsPanelView):
    """Owner-protected settings panel for Aishu's supported Discord profile."""

    def __init__(self, guild, owner_id: int):
        super().__init__(guild)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("owner only!", ephemeral=True)
        return False

    @discord.ui.button(label="🌸 Discord Name", style=discord.ButtonStyle.primary, row=2)
    async def discord_name(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(BotUsernameModal())

    @discord.ui.button(label="🖼️ Avatar / Banner", style=discord.ButtonStyle.secondary, row=2)
    async def avatar_help(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(
            "Attach an image with `/setprofile` to update Aishu's avatar or banner. "
            "For prefix use, attach it to `!setprofile`.", ephemeral=True,
        )


def _panel_embed(guild) -> discord.Embed:
    embed = discord.Embed(
        title       = "🌸 Aishu Settings Panel",
        description = "Customize personality, mood, and behavior.",
        color       = 0xFF69B4,
    )
    embed.add_field(name="Name",        value=aishu_state.name,           inline=True)
    embed.add_field(name="Age",         value=str(aishu_state.age),       inline=True)
    embed.add_field(name="Mood",
                    value=f"{aishu_state.mood.mood} {aishu_state.mood.emoji}", inline=True)
    embed.add_field(name="Stability",   value=f"{aishu_state.mood.stability:.1f}", inline=True)
    embed.add_field(name="Intensity",   value=f"{aishu_state.mood.intensity:.0%}", inline=True)
    embed.add_field(name="Energy",      value=f"{aishu_state.mood.energy:.0%}", inline=True)
    embed.add_field(name="Personality", value=aishu_state.personality,    inline=False)
    embed.add_field(name="Likes",       value=aishu_state.likes,          inline=True)
    embed.add_field(name="Dislikes",    value=aishu_state.dislikes,       inline=True)
    embed.add_field(name="Lover",       value=aishu_state.lover_name or "none",   inline=True)
    embed.add_field(name="Partner",     value=aishu_state.partner_name or "none", inline=True)
    embed.add_field(name="Status",      value=aishu_state.status_text,            inline=True)
    if aishu_state.custom_note:
        embed.add_field(name="Custom Note", value=aishu_state.custom_note, inline=False)
    if guild:
        auto_ch = aishu_state.get_auto_channel(guild.id)
        embed.add_field(
            name  = "Auto-Reply Channel",
            value = f"<#{auto_ch}>" if auto_ch else "None set",
            inline= True,
        )
    embed.set_footer(text="Changes apply immediately 🌸")
    return embed


def _profile_settings_embed(bot: commands.Bot, guild) -> discord.Embed:
    embed = _panel_embed(guild)
    embed.title = "🌸 Aishu Profile Studio"
    embed.description = "Edit Aishu's identity, personality, presence, and supported Discord profile assets."
    if bot.user:
        embed.set_thumbnail(url=bot.user.display_avatar.url)
        embed.set_author(name=f"Managing {bot.user}", icon_url=bot.user.display_avatar.url)
    embed.set_footer(text="Discord name, avatar, and banner use Discord's official bot profile API 🌸")
    return embed


async def _update_discord_profile_asset(
    interaction: discord.Interaction, attachment: discord.Attachment | None, field: str,
) -> str | None:
    if attachment is None:
        return None
    is_image = (attachment.content_type or "").startswith("image/") or attachment.filename.lower().endswith(
        (".png", ".jpg", ".jpeg", ".webp", ".gif")
    )
    if not is_image:
        return f"{field.capitalize()} must be an image attachment."
    if attachment.size > 8 * 1024 * 1024:
        return f"{field.capitalize()} must be 8 MB or smaller."
    try:
        await interaction.client.user.edit(**{field: await attachment.read()})
    except discord.HTTPException as exc:
        return f"Discord could not update the {field}: {exc.text or 'try again later.'}"
    except discord.DiscordException as exc:
        return f"Could not read the {field}: {exc}"
    return None


async def _update_discord_profile_assets(
    interaction: discord.Interaction,
    avatar: discord.Attachment | None,
    banner: discord.Attachment | None,
) -> list[str]:
    """Validate and update requested profile images in one Discord API call."""
    changes: dict[str, bytes] = {}
    errors: list[str] = []
    for field, attachment in (("avatar", avatar), ("banner", banner)):
        if attachment is None:
            continue
        is_image = (attachment.content_type or "").startswith("image/") or attachment.filename.lower().endswith(
            (".png", ".jpg", ".jpeg", ".webp", ".gif")
        )
        if not is_image:
            errors.append(f"{field.capitalize()} must be an image attachment.")
        elif attachment.size > 8 * 1024 * 1024:
            errors.append(f"{field.capitalize()} must be 8 MB or smaller.")
        else:
            try:
                changes[field] = await attachment.read()
            except discord.DiscordException as exc:
                errors.append(f"Could not read the {field}: {exc}")
    if changes:
        try:
            await interaction.client.user.edit(**changes)
        except discord.HTTPException as exc:
            errors.append(f"Discord could not update the profile: {exc.text or 'try again later.'}")
    return errors


async def _update_discord_profile_asset_from_attachment(
    bot: commands.Bot, attachment: discord.Attachment | None, field: str,
) -> str | None:
    if attachment is None:
        return None
    is_image = (attachment.content_type or "").startswith("image/") or attachment.filename.lower().endswith(
        (".png", ".jpg", ".jpeg", ".webp", ".gif")
    )
    if not is_image:
        return f"{field.capitalize()} must be an image attachment."
    if attachment.size > 8 * 1024 * 1024:
        return f"{field.capitalize()} must be 8 MB or smaller."
    try:
        await bot.user.edit(**{field: await attachment.read()})
    except discord.HTTPException as exc:
        return f"Discord could not update the {field}: {exc.text or 'try again later.'}"
    except discord.DiscordException as exc:
        return f"Could not read the {field}: {exc}"
    return None


# ─── Admin Cog ────────────────────────────────────────────────────────────────

class AdminCog(commands.Cog, name="Admin"):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # /aishu_panel
    @app_commands.command(name="aishu_panel",
                  description="🌸 Open Aishu's settings panel (Owner only)")
    async def panel(self, interaction: discord.Interaction):
        if not _owner_only(interaction):
            await interaction.response.send_message("owner only!", ephemeral=True); return
        embed = _panel_embed(interaction.guild)
        view  = SettingsPanelView(interaction.guild)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="setprofile", description="Open Aishu's Discord profile settings (Owner)")
    @app_commands.describe(
        avatar="Optional image attachment for Aishu's Discord avatar",
        banner="Optional image attachment for Aishu's Discord banner",
    )
    async def setprofile(
        self,
        interaction: discord.Interaction,
        avatar: discord.Attachment | None = None,
        banner: discord.Attachment | None = None,
    ):
        if not _owner_only(interaction):
            await interaction.response.send_message("owner only!", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=bool(avatar or banner))
        errors = await _update_discord_profile_assets(interaction, avatar, banner)
        embed = _profile_settings_embed(self.bot, interaction.guild)
        if avatar or banner:
            embed.add_field(
                name="Profile asset update",
                value="\n".join(f"⚠️ {error}" for error in errors) or "✅ Discord profile asset updated.",
                inline=False,
            )
        await interaction.followup.send(
            embed=embed,
            view=ProfileSettingsView(interaction.guild, interaction.user.id),
            ephemeral=True,
        )

    # /setchannel
    @app_commands.command(name="setchannel",
                  description="Set channel where Aishu auto-replies (Admin)")
    @app_commands.describe(channel="Leave blank to use current channel")
    @app_commands.default_permissions(administrator=True)
    async def setchannel(self, interaction: discord.Interaction,
                         channel: discord.TextChannel = None):
        ch = channel or interaction.channel
        aishu_state.set_auto_channel(interaction.guild.id, ch.id)
        await interaction.response.send_message(
            f"✅ Aishu will auto-reply in {ch.mention}!", ephemeral=True)

    # /removechannel
    @app_commands.command(name="removechannel",
                  description="Disable Aishu's auto-reply channel (Admin)")
    @app_commands.default_permissions(administrator=True)
    async def removechannel(self, interaction: discord.Interaction):
        aishu_state.set_auto_channel(interaction.guild.id, None)
        await interaction.response.send_message(
            "✅ Auto-reply disabled. Use `!aishu` or @mention me.", ephemeral=True)

    # /announce
    @app_commands.command(name="announce",
                  description="Make Aishu send an announcement (Admin)")
    @app_commands.describe(message="What to announce",
                           channel="Channel (default: current)")
    @app_commands.default_permissions(administrator=True)
    async def announce(self, interaction: discord.Interaction, message: str,
                       channel: discord.TextChannel = None):
        ch    = channel or interaction.channel
        embed = discord.Embed(description=message, color=0xFF69B4)
        embed.set_footer(text=f"— {aishu_state.name}")
        await ch.send(embed=embed)
        await interaction.response.send_message(
            f"✅ Announced in {ch.mention}!", ephemeral=True)

    # /guildconfig
    @app_commands.command(name="guildconfig",
                  description="View or edit guild settings (Admin)")
    @app_commands.default_permissions(administrator=True)
    async def guildconfig(self, interaction: discord.Interaction):
        gc = memory_manager.get_guild_config(
            interaction.guild.id, interaction.guild.name)
        embed = discord.Embed(
            title = f"Guild Config — {interaction.guild.name}",
            color = 0x5865F2,
        )
        auto_ch = gc.auto_reply_channel
        embed.add_field(name="Auto-Reply Channel",
                        value=f"<#{auto_ch}>" if auto_ch else "None", inline=True)
        embed.add_field(name="Memory",
                        value="✅ Enabled" if gc.memory_enabled else "❌ Disabled",
                        inline=True)
        embed.add_field(name="Leaderboard",
                        value="✅" if gc.leaderboard_enabled else "❌", inline=True)
        embed.add_field(name="Cooldown",
                        value=f"{gc.cooldown_seconds}s", inline=True)
        embed.add_field(name="Relationship Mode",
                        value=gc.relationship_mode, inline=True)
        embed.add_field(name="Created",
                        value=gc.created_at[:10], inline=True)
        embed.set_footer(text="Use /setchannel to configure auto-reply channel")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # /setlover
    @app_commands.command(name="setlover",
                  description="Set Aishu's special person (Owner)")
    @app_commands.describe(member="The member to set as Aishu's special person")
    async def setlover(self, interaction: discord.Interaction, member: discord.Member):
        if not _owner_only(interaction):
            await interaction.response.send_message("owner only!", ephemeral=True); return
        aishu_state.set_lover(member.id, member.display_name)
        embed = discord.Embed(
            title       = "🌸 Aishu's Lover Updated",
            description = f"Aishu now considers **{member.mention}** her special person 💕",
            color       = 0xFF69B4,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="💮 Name",       value=member.display_name, inline=True)
        embed.add_field(name="🤍 Discord ID", value=f"`{member.id}`",    inline=True)
        embed.set_footer(text="Aishu will be extra warm to them from now on 🌸")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # /setpartner
    @app_commands.command(name="setpartner",
                  description="Set Aishu's life partner — highest possible bond (Owner)")
    @app_commands.describe(member="The member to set as Aishu's life partner")
    async def setpartner(self, interaction: discord.Interaction, member: discord.Member):
        if not _owner_only(interaction):
            await interaction.response.send_message("owner only!", ephemeral=True); return
        aishu_state.set_partner(member.id, member.display_name)
        embed = discord.Embed(
            title       = "💞 Aishu's Life Partner Set",
            description = (
                f"**{member.mention}** is now Aishu's life partner.\n\n"
                f"This is the deepest bond possible. Aishu will route their messages "
                f"through uncensored HuggingFace models and respond with no walls, no filter."
            ),
            color       = 0xFF1493,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="💮 Name",       value=member.display_name, inline=True)
        embed.add_field(name="🤍 Discord ID", value=f"`{member.id}`",    inline=True)
        embed.add_field(
            name  = "⚠️ Note",
            value = "Make sure `HF_API_KEY` is set in `config/settings.py` for the partner model route.",
            inline= False,
        )
        embed.set_footer(text="Partner tier — rarest bond possible 💞")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # /clearpartner
    @app_commands.command(name="clearpartner",
                  description="Clear Aishu's life partner (Owner)")
    async def clearpartner(self, interaction: discord.Interaction):
        if not _owner_only(interaction):
            await interaction.response.send_message("owner only!", ephemeral=True); return
        old = aishu_state.partner_name or "nobody"
        aishu_state.clear_partner()
        await interaction.response.send_message(
            f"💔 Partner cleared. ({old} is no longer Aishu's partner)", ephemeral=True)

    # /family
    @app_commands.command(name="family",
                  description="Learn about Aishu's family 🌸")
    async def family(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title       = "🌸 Aishu's Family",
            description = "the people she grew up with and loves ♡",
            color       = 0xFF69B4,
        )
        embed.set_thumbnail(url=interaction.client.user.display_avatar.url)
        embed.add_field(
            name  = "👑 Creator & Maker — Raghul M",
            value = "her creator and bro who built her world, coded her mind, and brought her to life.",
            inline= False,
        )
        embed.add_field(
            name  = "🤍 Big Brother — RavenAI",
            value = "calm, smart, and protective. aishu looks up to him even though she teases him constantly.",
            inline= False,
        )
        embed.add_field(
            name  = "✨ Older Sister — Mia",
            value = "bubbly, fashionable, loves music and drama. they're thick as thieves but compete over everything.",
            inline= False,
        )
        embed.add_field(
            name  = f"🌷 Herself — {aishu_state.name}",
            value = "the youngest. most emotional, most curious. still figuring out who she is, one chat at a time.",
            inline= False,
        )
        embed.add_field(
            name  = "💮 Home",
            value = "the internet — wherever there are people to talk to 🌸",
            inline= False,
        )
        embed.set_footer(text="she mentions them sometimes naturally in conversation • created by Raghul M~")
        await interaction.response.send_message(embed=embed)

    # /models
    @app_commands.command(name="models",
                  description="Show AI models available to Aishu 🌸")
    async def models(self, interaction: discord.Interaction):
        best  = model_controller.best_model()

        def _short(m: str) -> str:
            return m.split("/")[-1].replace(":free", "") if "/" in m else m

        capability_groups = (
            ("💬 Chat", cfg.NVIDIA_NIM_MODELS["chat"]),
            ("🧠 Reasoning", cfg.NVIDIA_NIM_MODELS["reasoning"]),
            ("💻 Coding", cfg.NVIDIA_NIM_MODELS["coding"]),
            ("⚡ Fast fallback", cfg.GROQ_MODELS),
            ("🌐 Free router", cfg.FREE_MODELS),
        )
        total = sum(len(models) for _, models in capability_groups)

        embed = discord.Embed(
            title       = "🌸 Aishu AI Models",
            description = f"**{total}** configured models across task-specific routes",
            color       = 0xFF69B4,
        )
        embed.set_thumbnail(url=interaction.client.user.display_avatar.url)
        embed.add_field(
            name  = "✨ Current Best",
            value = f"`{_short(best)}`",
            inline= False,
        )
        for name, models in capability_groups:
            if models:
                embed.add_field(
                    name=name,
                    value="\n".join(f"• `{_short(m)}`" for m in models),
                    inline=True,
                )
        if cfg.OPENROUTER_RATE_LIMITED_MODELS:
            embed.add_field(
                name="🧊 Rate-limited reserve",
                value="\n".join(f"• `{_short(m)}`" for m in cfg.OPENROUTER_RATE_LIMITED_MODELS),
                inline=False,
            )
        embed.set_footer(text="Aishu routes by task and skips models that leak reasoning or are cooling down 🌸")
        await interaction.response.send_message(embed=embed)

    # /privacy
    @app_commands.command(name="privacy",
                  description="See what data Aishu stores about you 🌸")
    async def privacy(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title       = "🌸 Aishu Privacy Info",
            description = "Aishu stores limited data to remember you and improve conversations.",
            color       = 0xFF69B4,
        )
        embed.set_thumbnail(url=interaction.client.user.display_avatar.url)
        embed.add_field(
            name  = "✨ What Aishu stores",
            value = (
                "• memories and facts you share in conversation\n"
                "• your preferences and topics you care about\n"
                "• your relationship score with Aishu\n"
                "• interaction stats (message count, streaks, first/last seen)"
            ),
            inline= False,
        )
        embed.add_field(
            name  = "💮 What Aishu does NOT store",
            value = (
                "• full message history\n"
                "• passwords, emails, or sensitive personal data\n"
                "• data is never shared with third parties"
            ),
            inline= False,
        )
        embed.add_field(
            name  = "🌷 Your controls",
            value = (
                "`/forget <topic>` — remove a specific memory\n"
                "`/clear` — wipe your STM + LTM\n"
                "`/memories` — see everything Aishu remembers\n"
                "`/export` — download your data as a JSON file"
            ),
            inline= False,
        )
        embed.set_footer(text="your data is stored locally on Aishu's server only 🌸")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # /inspect
    @app_commands.command(name="inspect",
                  description="🌸 Debug Aishu's AI context for a user (Owner)")
    @app_commands.describe(member="The member to inspect (defaults to yourself)")
    async def inspect(self, interaction: discord.Interaction,
                      member: discord.Member = None):
        if not _owner_only(interaction):
            await interaction.response.send_message("owner only!", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)

        target   = member or interaction.user
        uid      = target.id
        guild_id = interaction.guild.id if interaction.guild else 0

        # Load user memory (read-only — does not change anything)
        um = memory_manager.load(uid, str(target), target.display_name)

        # Read relationship state
        score    = aishu_state.relationships.get_score(guild_id, uid)
        rs       = aishu_state.relationships.get_state(guild_id, uid)
        rel_tier = aishu_state.relationships.get_tier(guild_id, uid) if rs else "stranger"

        # Estimate token counts (1 token ≈ 4 chars)
        from brain.memory_optimizer import memory_optimizer
        identity_tokens    = len(cfg.AISHU_CORE_IDENTITY) // 4
        personality_tokens = len(aishu_state.build_personality_block()) // 4
        mem_context        = memory_optimizer.build_context(um, token_budget=600)
        memory_tokens      = len(mem_context) // 4 if mem_context else 0
        stm_tokens         = sum(len(str(m)) for m in um.stm) // 4
        total_est          = identity_tokens + personality_tokens + memory_tokens + stm_tokens + 30

        # Best/current model
        best = model_controller.best_model()

        # Memory snippets (last 5 LTM facts)
        snippets = [m.content[:70] for m in um._ltm_facts[-5:]]

        embed = discord.Embed(
                title       = "🌸 Aishu Brain Inspect",
            description = f"Context snapshot for **{target.display_name}**",
            color       = 0xFF69B4,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(
            name  = "✨ Current Best Model",
            value = f"`{best.split('/')[-1].replace(':free','') if '/' in best else best}`",
            inline= False,
        )
        embed.add_field(
            name  = "💮 Token Estimates",
            value = (
                f"Identity: **~{identity_tokens}**\n"
                f"Personality: **~{personality_tokens}**\n"
                f"Memory context: **~{memory_tokens}**\n"
                f"Short-term msgs: **~{stm_tokens}**\n"
                f"Total (est): **~{total_est}**"
            ),
            inline= True,
        )
        embed.add_field(
            name  = "🌷 User Stats",
            value = (
                f"Messages: **{um.message_count}**\n"
                f"LTM facts: **{len(um._ltm_facts)}**\n"
                f"LTM prefs: **{len(um._ltm_prefs)}**\n"
                f"STM msgs: **{len(um.stm)}**"
            ),
            inline= True,
        )
        embed.add_field(
            name  = "🤍 Relationship",
            value = (
                f"Score: **{score:.0f} pts**\n"
                f"Tier: **{rel_tier}**\n"
                f"Partner: **{'yes 💞' if aishu_state.is_partner(uid) else 'no'}**\n"
                f"Lover: **{'yes 💕' if aishu_state.is_lover(uid) else 'no'}**"
            ),
            inline= True,
        )
        embed.add_field(
            name  = "🌸 Mood",
            value = (
                f"{aishu_state.mood.mood} {aishu_state.mood.emoji} "
                f"(score {aishu_state.mood.score}, "
                f"energy {aishu_state.mood.energy:.0%})"
            ),
            inline= False,
        )
        if snippets:
            embed.add_field(
                name  = "📌 Active Memory Snippets",
                value = "\n".join(f"• {s}" for s in snippets),
                inline= False,
            )
        else:
            embed.add_field(
                name  = "📌 Memory Snippets",
                value = "no long-term memories stored yet",
                inline= False,
            )
        embed.set_footer(text="read-only — this command does not affect Aishu's state 🌸")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # /setmood
    @app_commands.command(name="setmood", description="Force Aishu's mood (Owner)")
    @app_commands.choices(mood=[
        app_commands.Choice(
            name=f"{MOOD_EMOJIS.get(m, '🌸')} {m.capitalize()}", value=m,
        ) for m in ALL_MOODS
    ])
    async def setmood(self, interaction: discord.Interaction, mood: str):
        if not _owner_only(interaction):
            await interaction.response.send_message("owner only!", ephemeral=True); return
        aishu_state.mood.force_mood(mood)
        aishu_state.save(force=True)
        await interaction.response.send_message(
            f"Mood set to **{mood}** {MOOD_EMOJIS.get(mood, '🌸')}", ephemeral=True)

    # /setstatus
    @app_commands.command(name="setstatus",
                  description="Change bot status text (Owner)")
    async def setstatus(self, interaction: discord.Interaction, text: str):
        if not _owner_only(interaction):
            await interaction.response.send_message("owner only!", ephemeral=True); return
        aishu_state.set("status_text", text, force_save=True)
        await self.bot.change_presence(activity=discord.Game(name=text))
        await interaction.response.send_message(f"✅ Status: `{text}`", ephemeral=True)

    def _stats_embed(self) -> discord.Embed:
        status = brain_router.get_status()
        model_report = model_controller.get_status_report()[:5]

        embed = discord.Embed(title="📊 AIshu Runtime Stats", color=0x5865F2)
        embed.add_field(name="Mood",
                        value=f"{status['mood']} {aishu_state.mood.emoji}", inline=True)
        embed.add_field(name="Score",     value=str(status['mood_score']),    inline=True)
        embed.add_field(name="Intensity", value=f"{status['mood_intensity']:.0%}", inline=True)
        embed.add_field(name="Energy",    value=f"{status['mood_energy']:.0%}",    inline=True)
        embed.add_field(name="Partner",   value=aishu_state.partner_name or "none", inline=True)
        embed.add_field(name="Lover",     value=status['lover'] or "none",    inline=True)
        embed.add_field(name="Users",     value=str(status['users_loaded']),  inline=True)
        embed.add_field(name="Memory OK", value="✅" if status['memory_ok'] else "❌", inline=True)
        embed.add_field(name="Guilds",    value=str(len(self.bot.guilds)),    inline=True)
        best_val = (status["best_model"].split("/")[-1][:25]
                    if status["best_model"] else "None available")
        embed.add_field(name="Best Model", value=best_val, inline=True)

        if model_report:
            lines = []
            for m in model_report:
                short = m["model"].split("/")[-1][:28] if "/" in m["model"] else m["model"][:28]
                lines.append(
                    f"`{short}` — "
                    f"{m['successes']}✅ {m['failures']}❌ "
                    f"avg {m['avg_latency_ms']:.0f}ms "
                    f"({m['success_rate']:.0%})"
                )
            embed.add_field(
                name="Top Models (by rank)", value="\n".join(lines), inline=False)
        return embed

    # /stats
    @app_commands.command(name="stats", description="Show runtime stats (Owner)")
    async def stats(self, interaction: discord.Interaction):
        if not _owner_only(interaction):
            await interaction.response.send_message("owner only!", ephemeral=True); return
        embed = self._stats_embed()
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # /adminreset — owner-only global wipe of ALL users' memory
    @app_commands.command(name="adminreset",
                  description="⚠️ OWNER ONLY — Wipe ALL users' memory data globally")
    async def adminreset(self, interaction: discord.Interaction):
        if not _owner_only(interaction):
            await interaction.response.send_message("owner only!", ephemeral=True); return

        user_count = memory_manager.user_count()

        class ConfirmResetView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=30)
                self.confirmed = False

            @discord.ui.button(label="⚠️ Yes, Wipe Everything", style=discord.ButtonStyle.danger)
            async def confirm(self_inner, btn_interaction: discord.Interaction, button):
                if btn_interaction.user.id != interaction.user.id:
                    await btn_interaction.response.send_message(
                        "only the owner can confirm this!", ephemeral=True)
                    return
                self_inner.confirmed = True
                memory_manager.clear_all_users()
                aishu_state.relationships = RelationshipSystem()
                aishu_state.clear_lover()
                aishu_state.clear_partner()
                aishu_state.flush()
                self_inner.stop()
                done_embed = discord.Embed(
                    title       = "🌸 Global Memory Wipe Complete",
                    description = (
                        f"all user memory data has been permanently cleared ✨\n\n"
                        f"**{user_count}** user{'s' if user_count != 1 else ''} "
                        f"wiped across the entire bot.\n\n"
                        f"every conversation, every memory — gently released 💗"
                    ),
                    color       = 0xFFB7C5,
                )
                done_embed.set_footer(text="this action cannot be undone  •  users will start fresh on next interaction 🌸")
                await btn_interaction.response.edit_message(embed=done_embed, view=None)

            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
            async def cancel(self_inner, btn_interaction: discord.Interaction, button):
                if btn_interaction.user.id != interaction.user.id:
                    await btn_interaction.response.send_message(
                        "only the owner can cancel this!", ephemeral=True)
                    return
                self_inner.stop()
                cancel_embed = discord.Embed(
                    title       = "✨ Cancelled",
                    description = "no data was deleted 🌸\neveryone's memories are safe.",
                    color       = 0xE8D5E8,
                )
                cancel_embed.set_footer(text="phew~ nothing was changed 🌸")
                await btn_interaction.response.edit_message(embed=cancel_embed, view=None)

        confirm_embed = discord.Embed(
            title       = "⚠️ Global Memory Wipe — Are You Sure?",
            description = (
                f"this will **permanently delete every user's memory data** "
                f"across the entire bot.\n\n"
                f"💗 **{user_count}** user{'s' if user_count != 1 else ''} currently in memory\n\n"
                f"every fact, preference, and long-term memory will be gone forever.\n"
                f"⚠️ **this cannot be undone.**"
            ),
            color       = 0xFF6B8A,
        )
        confirm_embed.set_footer(text="confirmation expires in 30 seconds  •  only the owner can confirm 🌸")
        await interaction.response.send_message(
            embed=confirm_embed, view=ConfirmResetView(), ephemeral=True)

    # ─── Developer prefix commands ────────────────────────────────────────────

    @commands.command(name="probe")
    async def probe_cmd(self, ctx: commands.Context):
        """Run model diagnostics. Owner only."""
        if ctx.author.id != cfg.BOT_OWNER_ID:
            await ctx.send("owner only 🚫"); return
        msg = await ctx.send("🔍 probing all models... this may take a minute...")
        async with ctx.typing():
            loop    = asyncio.get_running_loop()
            results = await loop.run_in_executor(None, model_controller.probe_all_models)

        embed = discord.Embed(
            title       = "🔬 Model Probe Results",
            description = f"Tested {len(results)} models — rankings saved to disk",
            color       = 0x5865F2,
        )
        active = [r for r in results if "✅" in r["status"]]
        failed = [r for r in results if "❌" in r["status"]]

        if active:
            text = "\n".join(
                f"✅ `{r['short_name']}` — {r['latency_ms']}ms"
                for r in active[:12]
            )
            embed.add_field(name=f"Active ({len(active)})", value=text[:1000], inline=False)
        if failed:
            text = "\n".join(f"❌ `{r['short_name']}`" for r in failed[:8])
            embed.add_field(name=f"Failed ({len(failed)})", value=text[:500], inline=False)

        await msg.edit(content=None, embed=embed)

    @commands.command(name="brain")
    async def brain_cmd(self, ctx: commands.Context):
        """Show brain status JSON. Owner only."""
        if ctx.author.id != cfg.BOT_OWNER_ID:
            await ctx.send("owner only 🚫"); return
        status = brain_router.get_status()
        await ctx.send(f"```json\n{json.dumps(status, indent=2)}\n```")

    @commands.command(name="memorycheck", aliases=["memcheck"])
    async def memcheck_cmd(self, ctx: commands.Context, user_id: int = 0):
        """Inspect a user's raw memory. Owner only."""
        if ctx.author.id != cfg.BOT_OWNER_ID:
            await ctx.send("owner only 🚫"); return
        tid = user_id or ctx.author.id
        um  = memory_manager.load(tid, str(tid), str(tid))
        data = {
            "user_id":    um.user_id,
            "username":   um.username,
            "messages":   um.message_count,
            "stm_count":  len(um.stm),
            "utm_count":  len(um.utm),
            "ltm_facts":  [
                {"content": m.content[:60], "imp": m.importance, "hits": m.mention_count}
                for m in um._ltm_facts[-5:]
            ],
            "ltm_prefs":  [
                {"content": m.content[:60], "imp": m.importance}
                for m in um._ltm_prefs[-5:]
            ],
        }
        js = json.dumps(data, indent=2, ensure_ascii=False)
        if len(js) > 1900:
            js = js[:1900] + "\n..."
        await ctx.send(f"```json\n{js}\n```")

    @commands.command(name="modelstatus")
    async def modelstatus_cmd(self, ctx: commands.Context):
        """Show persistent model ranking report. Owner only."""
        if ctx.author.id != cfg.BOT_OWNER_ID:
            await ctx.send("owner only 🚫"); return
        report = model_controller.get_status_report()
        if not report:
            await ctx.send("No ranking data yet — run `!probe` first."); return
        lines = []
        for r in report[:15]:
            short = r["model"].split("/")[-1][:30] if "/" in r["model"] else r["model"][:30]
            lines.append(
                f"`{short}` {r['successes']}✅ {r['failures']}❌ "
                f"avg {r['avg_latency_ms']:.0f}ms ({r['success_rate']:.0%})"
                + (" [disabled]" if r.get("manually_disabled") else "")
                + ("" if r.get("is_active", True) else " ⚠️ inactive")
            )
        embed = discord.Embed(
            title       = "📈 Model Rankings (persistent)",
            description = "\n".join(lines) or "no data",
            color       = 0x5865F2,
        )
        embed.set_footer(text="Rankings survive restarts • run !probe to refresh")
        await ctx.send(embed=embed)

    @commands.command(name="rankingsave")
    async def rankingsave_cmd(self, ctx: commands.Context):
        """Force-save model rankings to disk. Owner only."""
        if ctx.author.id != cfg.BOT_OWNER_ID:
            await ctx.send("owner only 🚫"); return
        model_controller._save_rankings()
        await ctx.send("✅ Rankings saved to disk.")

    @commands.command(name="setprofile", aliases=["aishuprofile"])
    async def setprofile_cmd(self, ctx: commands.Context):
        """Open Aishu's profile studio; attach an image to update her avatar."""
        if ctx.author.id != cfg.BOT_OWNER_ID:
            await ctx.send("owner only!", delete_after=4)
            return
        avatar = ctx.message.attachments[0] if ctx.message.attachments else None
        error = await _update_discord_profile_asset_from_attachment(ctx.bot, avatar, "avatar")
        embed = _profile_settings_embed(self.bot, ctx.guild)
        if avatar:
            embed.add_field(
                name="Avatar update",
                value=f"⚠️ {error}" if error else "✅ Discord avatar updated.",
                inline=False,
            )
        await ctx.send(embed=embed, view=ProfileSettingsView(ctx.guild, ctx.author.id))

    @commands.command(name="family")
    async def family_cmd(self, ctx: commands.Context):
        """Learn about Aishu's family and creator."""
        embed = discord.Embed(
            title="🌸 Aishu's Family & Creator",
            description=(
                "Aishu isn't just an AI — she has a loving family and creator!\n\n"
                "👑 **Raghul M** — Creator & Maker\n"
                "• Her developer, creator, and bro who brought her to life\n"
                "• Designed her mind, emotions, and memory\n\n"
                "🦅 **RavenAI** — Older brother\n"
                "• Calm, wise, and protective\n"
                "• Focuses on reasoning, depth, and clarity\n\n"
                "✨ **Mia** — Older sister\n"
                "• Creative, emotional, and expressive\n"
                "• Loves writing, art, and exploring feelings\n\n"
                "🌸 **Aishu** — The youngest!\n"
                "• Playful, observant, sweet, and genuine\n"
                "• Loves tea, cozy vibes, and staying close"
            ),
            color=0xFFB7C5,
        )
        embed.set_footer(text="Aishu ✿ • created by Raghul M • family lore")
        await ctx.send(embed=embed)

    @commands.command(name="models")
    async def models_cmd(self, ctx: commands.Context):
        """Show active AI models across routes."""
        candidates = model_controller.probe_candidates()
        best = model_controller.best_model() or "auto"
        embed = discord.Embed(
            title="🤖 Aishu's Model Ecosystem",
            description=(
                f"**Active Routes:** NVIDIA NIM, Gemini, Groq, Cloudflare Workers AI, OpenRouter\n"
                f"**Current Best Model:** `{best}`\n"
                f"**Total Model Candidates:** `{len(candidates)}`\n\n"
                "Aishu dynamically benchmarks and routes to the fastest healthy model with sub-second latency!"
            ),
            color=0x5865F2,
        )
        await ctx.send(embed=embed)

    @commands.command(name="privacy")
    async def privacy_cmd(self, ctx: commands.Context):
        """Data storage and privacy controls."""
        embed = discord.Embed(
            title="🔒 Privacy & Data Policy",
            description=(
                "**What Aishu Remembers:**\n"
                "• Facts and preferences you mention in conversation (e.g. favorite foods, pets)\n"
                "• Relationship bond scores and conversation streaks\n\n"
                "**Privacy Guarantees:**\n"
                "• Data is stored locally in SQLite (`data/aishu.db`) on the host server\n"
                "• Never sold, scraped, or shared with third parties\n"
                "• In Group DMs, memories are strictly isolated and never leaked to others\n\n"
                "**Your Controls:**\n"
                f"• `{cfg.PREFIX}memories` — view your stored data\n"
                f"• `{cfg.PREFIX}forget <topic>` — delete specific memories\n"
                f"• `{cfg.PREFIX}clear` — wipe all your memory completely\n"
                f"• `{cfg.PREFIX}export` — download your data as a JSON file"
            ),
            color=0x57F287,
        )
        await ctx.send(embed=embed)

    @commands.command(name="stats")
    async def stats_cmd(self, ctx: commands.Context):
        """Show Aishu's global runtime metrics. Owner only."""
        if ctx.author.id != cfg.BOT_OWNER_ID:
            await ctx.send("owner only 🚫", delete_after=4); return
        embed = self._stats_embed()
        await ctx.send(embed=embed)

    @commands.command(name="setpartner")
    async def setpartner_cmd(self, ctx: commands.Context, member: discord.Member = None):
        """Set Aishu's life partner. Owner only."""
        if ctx.author.id != cfg.BOT_OWNER_ID:
            await ctx.send("owner only 🚫", delete_after=4); return
        if not member:
            await ctx.send(f"mention a user! e.g. `{cfg.PREFIX}setpartner @user`"); return
        aishu_state.set_partner(member.id, member.display_name)
        await ctx.send(f"💞 {member.display_name} is now Aishu's life partner!")

    @commands.command(name="clearpartner")
    async def clearpartner_cmd(self, ctx: commands.Context):
        """Clear Aishu's life partner. Owner only."""
        if ctx.author.id != cfg.BOT_OWNER_ID:
            await ctx.send("owner only 🚫", delete_after=4); return
        aishu_state.clear_partner()
        await ctx.send("life partner cleared.")

    @commands.command(name="setlover")
    async def setlover_cmd(self, ctx: commands.Context, member: discord.Member = None):
        """Set Aishu's special person. Owner only."""
        if ctx.author.id != cfg.BOT_OWNER_ID:
            await ctx.send("owner only 🚫", delete_after=4); return
        if not member:
            await ctx.send(f"mention a user! e.g. `{cfg.PREFIX}setlover @user`"); return
        aishu_state.set_lover(member.id, member.display_name)
        await ctx.send(f"💕 {member.display_name} is now Aishu's special person!")

    @commands.command(name="setmood")
    async def setmood_cmd(self, ctx: commands.Context, mood: str = ""):
        """Force Aishu's mood. Owner only."""
        if ctx.author.id != cfg.BOT_OWNER_ID:
            await ctx.send("owner only 🚫", delete_after=4); return
        valid = ["happy", "soft", "flirty", "excited", "playful", "neutral", "shy", "bored", "annoyed", "sad", "angry"]
        m = mood.strip().lower()
        if m not in valid:
            await ctx.send(f"valid moods: {', '.join(valid)}"); return
        aishu_state.mood.force_mood(m)
        aishu_state.save()
        await ctx.send(f"mood forced to: **{m}** {aishu_state.mood.emoji}")

    @commands.command(name="setstatus")
    async def setstatus_cmd(self, ctx: commands.Context, *, text: str = ""):
        """Change bot status text. Owner only."""
        if ctx.author.id != cfg.BOT_OWNER_ID:
            await ctx.send("owner only 🚫", delete_after=4); return
        status = text.strip() or f"with {cfg.PREFIX}help ♡"
        await self.bot.change_presence(activity=discord.CustomActivity(name=status))
        await ctx.send(f"status updated to: *\"{status}\"*")

    @commands.command(name="inspect")
    async def inspect_cmd(self, ctx: commands.Context, member: discord.Member = None):
        """Debug Aishu's AI context for a user. Owner only."""
        if ctx.author.id != cfg.BOT_OWNER_ID:
            await ctx.send("owner only 🚫", delete_after=4); return
        m = member or ctx.author
        um = memory_manager.load(m.id, str(m), m.display_name)
        embed = discord.Embed(title=f"🔬 Inspection: {m.display_name}", color=0x5865F2)
        embed.add_field(name="User ID", value=str(m.id), inline=True)
        embed.add_field(name="Message Count", value=str(um.message_count), inline=True)
        embed.add_field(name="Streak", value=f"{um.current_streak} days", inline=True)
        embed.add_field(name="STM", value=f"{len(um.stm)} messages", inline=True)
        embed.add_field(name="UTM", value=f"{len(um.utm)} candidate facts", inline=True)
        embed.add_field(name="LTM Facts", value=f"{len(um._ltm_facts)} items", inline=True)
        embed.add_field(name="LTM Prefs", value=f"{len(um._ltm_prefs)} items", inline=True)
        embed.add_field(name="RP Active", value=str(um.roleplay.is_active), inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="setchannel")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def setchannel_cmd(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Set auto-reply channel. Admin only."""
        ch = channel or ctx.channel
        aishu_state.set_auto_channel(ctx.guild.id, ch.id)
        await ctx.send(f"✅ Aishu will now automatically chat in {ch.mention}!")

    @commands.command(name="removechannel")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def removechannel_cmd(self, ctx: commands.Context):
        """Disable auto-reply channel. Admin only."""
        aishu_state.remove_auto_channel(ctx.guild.id)
        await ctx.send("✅ Auto-reply channel removed. Aishu will only reply when @mentioned.")

    @commands.command(name="announce")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def announce_cmd(self, ctx: commands.Context, *, message: str = ""):
        """Post an announcement embed. Admin only."""
        if not message.strip():
            await ctx.send(f"provide a message! e.g. `{cfg.PREFIX}announce Hello everyone!`"); return
        embed = discord.Embed(
            title=f"📢 Announcement from {ctx.guild.name}",
            description=message.strip(),
            color=0xFF69B4,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Sent by {ctx.author.display_name} • Aishu ✿")
        await ctx.send(embed=embed)

    @commands.command(name="guildconfig")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def guildconfig_cmd(self, ctx: commands.Context):
        """View guild settings. Admin only."""
        gc = memory_manager.get_guild_config(ctx.guild.id, ctx.guild.name)
        auto_ch = aishu_state.get_auto_channel(ctx.guild.id)
        quiet = memory_manager.is_quiet(ctx.channel.id, ctx.guild.id)
        embed = discord.Embed(title=f"⚙️ Configuration for {ctx.guild.name}", color=0x5865F2)
        embed.add_field(name="Auto-Reply Channel", value=f"<#{auto_ch}>" if auto_ch else "None (mentions only)", inline=True)
        embed.add_field(name="Quiet Mode", value="Enabled 🌙" if quiet else "Disabled 💬", inline=True)
        embed.add_field(name="Memory Enabled", value=str(gc.memory_enabled), inline=True)
        embed.add_field(name="Relationship Mode", value=gc.relationship_mode, inline=True)
        embed.add_field(name="Cooldown", value=f"{gc.cooldown_seconds}s", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="refreshmodel")
    async def refreshmodel_cmd(self, ctx: commands.Context):
        """Live probe and benchmark all AI models. Owner only."""
        if ctx.author.id != cfg.BOT_OWNER_ID:
            await ctx.send("owner only 🚫", delete_after=4); return
        msg = await ctx.send("🔍 benchmarking all models across providers...")
        async with ctx.typing():
            loop = asyncio.get_running_loop()
            results = await loop.run_in_executor(None, model_controller.probe_all_models)
        embed = discord.Embed(title="🔬 Model Benchmark Results", color=0x5865F2)
        active = [r for r in results if "✅" in r["status"]]
        failed = [r for r in results if "❌" in r["status"]]
        if active:
            embed.add_field(name=f"Active ({len(active)})", value="\n".join(f"✅ `{r['short_name']}` — {r['latency_ms']:.0f}ms" for r in active[:10]), inline=False)
        if failed:
            embed.add_field(name=f"Failed ({len(failed)})", value="\n".join(f"❌ `{r['short_name']}`" for r in failed[:8]), inline=False)
        embed.set_footer(text=f"Total: {len(results)} models • Rankings saved to disk")
        await msg.edit(content=None, embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
