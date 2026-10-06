"""
commands/refresh_model_cog.py — /refreshmodel command for Aishu bot.

Tests every FREE_MODELS entry one-by-one via OpenRouter,
updates a single embed live while probing, then edits it into a
ranked final result. Also persists the ranked list via model_controller.

Usage:
    Drop this file in commands/ and add to main.py:
        await bot.load_extension("commands.refresh_model_cog")
"""

import asyncio
import time
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import config.settings as cfg
from brain.model_controller import model_controller
from utilities.logger import get_logger

log = get_logger("commands.refresh_model")

# ── Constants ─────────────────────────────────────────────────────────────────

PROBE_PROMPT   = [{"role": "user", "content": "reply with ok"}]
PROBE_TIMEOUT  = 5.0     # seconds — hard cap per model
INTER_DELAY    = 0.6     # seconds between checks (avoid rate limits)
SLOW_THRESHOLD = 4.0     # seconds — above this = "slow" not "healthy"

# Embed colours
COLOR_LOADING = 0x5865F2   # Discord blurple
COLOR_GREEN   = 0x2ECC71
COLOR_YELLOW  = 0xF1C40F
COLOR_RED     = 0xE74C3C


# ── Data structure ─────────────────────────────────────────────────────────────

def _empty_result(name: str) -> dict:
    """Return a blank health record for one model."""
    return {
        "name":          name,
        "status":        "pending",   # pending | healthy | slow | failed | cooldown
        "response_time": 0.0,
        "error":         "",
    }


# ── Embed builders ─────────────────────────────────────────────────────────────

def _short(model: str) -> str:
    """Strip org prefix and :free suffix for display."""
    s = model.split("/")[-1] if "/" in model else model
    return s.replace(":free", "")


def build_loading_embed(
    results: list[dict],
    current_model: str,
    current_index: int,
    total: int,
) -> discord.Embed:
    """
    Live-updating embed shown while models are still being tested.

    Args:
        results:       Already-tested results (with final statuses).
        current_model: The model currently being probed.
        current_index: 1-based index of the current model.
        total:         Total number of models to test.
    """
    healthy  = sum(1 for r in results if r["status"] == "healthy")
    slow     = sum(1 for r in results if r["status"] == "slow")
    failed   = sum(1 for r in results if r["status"] == "failed")
    cooldown = sum(1 for r in results if r["status"] == "cooldown")

    embed = discord.Embed(
        title       = "🔄 Refreshing Model Status",
        description = "Testing model availability and latency...",
        color       = COLOR_LOADING,
    )

    embed.add_field(
        name   = "📊 Progress",
        value  = f"`{current_index} / {total}`",
        inline = True,
    )
    embed.add_field(
        name   = "🤖 Current Model",
        value  = f"`{_short(current_model)}`",
        inline = True,
    )
    embed.add_field(
        name  = "\u200b",   # empty spacer
        value = "\u200b",
        inline = True,
    )
    embed.add_field(
        name  = "📈 Status Summary",
        value = (
            f"✅ **{healthy}** healthy  •  "
            f"⚠️ **{slow}** slow  •  "
            f"❌ **{failed}** failed  •  "
            f"🧊 **{cooldown}** cooldown"
        ),
        inline = False,
    )

    embed.set_footer(text="Please wait — do not dismiss this message...")
    return embed


def build_result_embed(
    results: list[dict],
    total_duration: float,
) -> discord.Embed:
    """
    Final embed shown after all models have been tested.

    Args:
        results:        Full list of health dicts, already ranked best→worst.
        total_duration: Wall-clock seconds the whole probe took.
    """
    healthy = [r for r in results if r["status"] == "healthy"]
    slow    = [r for r in results if r["status"] == "slow"]
    failed  = [r for r in results if r["status"] in ("failed", "cooldown")]

    healthy_count = len(healthy)
    failed_count  = len(failed) + len(slow)   # "not fully healthy"
    total         = len(results)

    # Determine embed colour from health ratio
    ratio = healthy_count / total if total else 0
    if ratio >= 0.6:
        color = COLOR_GREEN
    elif ratio >= 0.3:
        color = COLOR_YELLOW
    else:
        color = COLOR_RED

    best_model = (results[0].get("name") or results[0].get("model")) if results else "N/A"

    # Average response time (healthy + slow only — failed have no real time)
    timed = [r.get("response_time", 0.0) for r in results
             if r.get("status") in ("healthy", "slow") and r.get("response_time", 0.0) > 0]
    avg_rt = sum(timed) / len(timed) if timed else 0.0

    embed = discord.Embed(
        title       = "✅ Model Refresh Complete",
        description = "Models ranked by performance and availability",
        color       = color,
    )

    # ── Summary field ────────────────────────────────────────────────────────
    embed.add_field(
        name  = "📋 Summary",
        value = (
            f"🏆 **Best Model:** `{_short(best_model)}`\n"
            f"✅ **Healthy:** {healthy_count} / {total}\n"
            f"❌ **Failed / Slow:** {failed_count}\n"
            f"⏱️ **Avg Response:** {avg_rt:.2f}s\n"
            f"🕐 **Total Duration:** {total_duration:.1f}s"
        ),
        inline = False,
    )

    # ── Ranked results (cap at 15 to stay within Discord field limit) ────────
    def _icon(status: str) -> str:
        return {"healthy": "✅", "slow": "⚠️", "failed": "❌", "cooldown": "🧊"}.get(status, "❓")

    def _time_str(r: dict) -> str:
        if r.get("status") in ("failed", "cooldown"):
            return r.get("error") or r.get("error_msg") or r.get("status", "failed")
        return f"{r.get('response_time', 0.0):.2f}s"

    ranked_lines = []
    for i, r in enumerate(results[:15], start=1):
        icon = _icon(r.get("status", "failed"))
        name = _short(r.get("name") or r.get("model") or "unknown")
        time_s = _time_str(r)
        ranked_lines.append(f"`{i:>2}.` {icon} `{name}` — {time_s}")

    if len(results) > 15:
        ranked_lines.append(f"*…and {len(results) - 15} more*")

    embed.add_field(
        name  = "🏅 Ranked Results",
        value = "\n".join(ranked_lines) or "No data",
        inline = False,
    )

    embed.set_footer(text="Rankings saved — Aishu will use the best models automatically 🌸")
    return embed


# ── Model health checker ───────────────────────────────────────────────────────

async def check_model(session: aiohttp.ClientSession, model: str) -> dict:
    """
    Send a tiny probe to one model and return its health dict.

    Detects:
        - success (healthy / slow based on SLOW_THRESHOLD)
        - timeout
        - rate limit (HTTP 429)
        - other API / network errors
    """
    result = _empty_result(model)
    start  = time.monotonic()

    try:
        async with session.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=cfg.OPENROUTER_HEADERS,
            json={
                "model":       model,
                "messages":    PROBE_PROMPT,
                "max_tokens":  10,
                "temperature": 0.1,
            },
            timeout=aiohttp.ClientTimeout(total=PROBE_TIMEOUT),
        ) as resp:

            elapsed = time.monotonic() - start

            # ── Rate limited ─────────────────────────────────────────────────
            if resp.status == 429:
                result["status"] = "cooldown"
                result["error"]  = "rate limited"
                log.warning(f"[refreshmodel] 429 rate limited: {_short(model)}")
                return result

            # ── Non-200 ──────────────────────────────────────────────────────
            if resp.status != 200:
                result["status"] = "failed"
                result["error"]  = f"HTTP {resp.status}"
                log.warning(f"[refreshmodel] HTTP {resp.status}: {_short(model)}")
                return result

            data = await resp.json(content_type=None)

            # ── API-level error in body ───────────────────────────────────────
            if "error" in data:
                code = data["error"].get("code", "?")
                msg  = data["error"].get("message", "unknown")[:60]
                result["status"] = "failed"
                result["error"]  = f"err {code}: {msg}"
                log.warning(f"[refreshmodel] API error {code} on {_short(model)}: {msg}")
                return result

            # ── Empty / missing content ──────────────────────────────────────
            choices = data.get("choices") or []
            content = ""
            if choices:
                content = (choices[0].get("message") or {}).get("content") or ""
            if not content.strip():
                result["status"] = "failed"
                result["error"]  = "empty response"
                return result

            # ── Success — classify healthy vs slow ───────────────────────────
            result["response_time"] = round(elapsed, 3)
            result["status"]        = "slow" if elapsed > SLOW_THRESHOLD else "healthy"
            log.info(
                f"[refreshmodel] {'healthy' if elapsed <= SLOW_THRESHOLD else 'slow'}: "
                f"{_short(model)} in {elapsed:.2f}s"
            )
            return result

    except asyncio.TimeoutError:
        result["status"] = "failed"
        result["error"]  = "timeout"
        log.warning(f"[refreshmodel] timeout: {_short(model)}")
        return result

    except aiohttp.ClientConnectionError as e:
        result["status"] = "failed"
        result["error"]  = "connection error"
        log.warning(f"[refreshmodel] connection error on {_short(model)}: {e}")
        return result

    except Exception as e:
        result["status"] = "failed"
        result["error"]  = str(e)[:60]
        log.error(f"[refreshmodel] unexpected error on {_short(model)}: {e}")
        return result


# ── Ranking helper ─────────────────────────────────────────────────────────────

def _rank_results(results: list[dict]) -> list[dict]:
    """
    Sort results best → worst.
    Order: healthy < slow < cooldown < failed
    Within healthy/slow: sort by response_time ascending.
    """
    STATUS_ORDER = {"healthy": 0, "slow": 1, "cooldown": 2, "failed": 3}

    return sorted(
        results,
        key=lambda r: (
            STATUS_ORDER.get(r["status"], 9),
            r["response_time"] if r["response_time"] > 0 else 9999.0,
        ),
    )


# ── Cog ───────────────────────────────────────────────────────────────────────

class RefreshModelCog(commands.Cog, name="RefreshModel"):
    """Cog that registers and handles the /refreshmodel slash command."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name        = "refreshmodel",
        description = "🔄 Test all AI models and refresh the ranking (Owner only)",
    )
    async def refreshmodel(self, interaction: discord.Interaction):
        # ── Owner-only guard ─────────────────────────────────────────────
        if interaction.user.id != cfg.BOT_OWNER_ID:
            await interaction.response.send_message(
                "❌ This command is owner only.", ephemeral=True
            )
            return

        # ModelController owns the complete provider-aware route list.
        # The previous implementation only tested FREE_MODELS (one router).
        models       = model_controller.probe_candidates()
        total        = len(models)
        completed    : list[dict] = []
        probe_start  = time.monotonic()

        if not models:
            await interaction.response.send_message(
                "no provider credentials are loaded — add them to `.env` and restart Aishu.",
                ephemeral=True,
            )
            return

        # ── Send initial loading embed ───────────────────────────────────
        loading_embed = build_loading_embed(
            results       = completed,
            current_model = models[0],
            current_index = 1,
            total         = total,
        )
        await interaction.response.send_message(embed=loading_embed)
        # Grab the message object so we can edit it later
        msg: discord.InteractionMessage = await interaction.original_response()

        for idx, model in enumerate(models, start=1):
            try:
                await msg.edit(embed=build_loading_embed(
                    results=completed, current_model=model,
                    current_index=idx, total=total,
                ))
            except discord.HTTPException:
                pass
            # The controller uses the exact same provider callers as chat,
            # so this verifies a real one-word completion, not just HTTP.
            completed.append(await asyncio.to_thread(model_controller.probe_model, model))
            if idx < total:
                await asyncio.sleep(INTER_DELAY)

        # ── All done — rank and build final embed ────────────────────────
        ranked         = _rank_results(completed)
        total_duration = time.monotonic() - probe_start

        # Feed results back into model_controller so rankings persist
        _sync_rankings_to_controller(ranked)

        final_embed = build_result_embed(
            results        = ranked,
            total_duration = total_duration,
        )

        try:
            await msg.edit(embed=final_embed)
        except discord.HTTPException as e:
            log.error(f"[refreshmodel] failed to edit final embed: {e}")

        log.info(
            f"[refreshmodel] done in {total_duration:.1f}s — "
            f"{sum(1 for r in ranked if r['status'] == 'healthy')} healthy / {total} total"
        )

        # Return the sorted list (available for future integration)
        return ranked


def _sync_rankings_to_controller(ranked: list[dict]):
    """
    Push the fresh probe results into model_controller's ranking store.
    This means /refreshmodel doubles as a full re-probe — rankings survive restarts.
    """
    # probe_model has already updated the authoritative records using the same
    # calls as normal chat. Save once; do not double-count probe successes.
    model_controller._save_rankings(force=True)
    log.info("[refreshmodel] rankings saved to disk via model_controller")


# ── Extension entry point ──────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(RefreshModelCog(bot))
