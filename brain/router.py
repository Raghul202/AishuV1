"""
brain/router.py — Brain Router with dynamic roleplay system.

Pipeline:
  RoutePacket
    → Memory load
    → Roleplay detection (start / end / resume)
    → Reasoning
    → Prompt build (roleplay-aware)
    → Model call (trimmed STM for roleplay)
    → Response processing
    → Core state updates + roleplay memory recording
    → ExecutionResult
"""

import asyncio
import time as _time

from brain.model_controller import model_controller
from brain.memory_optimizer import memory_optimizer
from brain.prompt_engine import prompt_engine
from brain.reasoning import reasoning_engine
from brain.response_engine import response_engine

from core.memory.memory_manager import memory_manager
from core.personality.aishu_state import aishu_state
from core.relationship.relationship_system import RelationshipSystem
from core.roleplay_manager import (
    is_rp_start, is_rp_end, is_rp_resume,
    extract_roles,
)
from core.schemas import (
    RoutePacket, ExecutionResult,
    FAIL_NO_MODEL,
    get_failure_message,
)
from utilities.logger import get_logger

log = get_logger("brain.router")

_PARTNER_SESSION_TIMEOUT = 7200.0

_NORMAL_MEMORY_HINTS = {
    "remember", "recall", "told", "said", "mentioned", "yesterday", "last time",
    "before", "earlier", "history", "favorite", "favourite", "project", "work",
    "did we", "did you", "what do you know", "what did", "remind me",
    "preference", "usual", "normally", "always", "never", "my name",
}


def _wants_normal_memory(text: str) -> bool:
    tl = text.lower()
    return any(hint in tl for hint in _NORMAL_MEMORY_HINTS)


def _memory_debug_counts(um) -> dict:
    return {
        "stm_messages":         len(um.get_stm_list()),
        "utm_entries":          len(um.utm),
        "ltm_facts":            len(um._ltm_facts),
        "ltm_prefs":            len(um._ltm_prefs),
        "ltm_topics":           len(um._ltm_topics),
        "partner_ltm_facts":    len(um._partner_ltm_facts),
        "partner_ltm_prefs":    len(um._partner_ltm_prefs),
        "partner_stm_messages": len(um.get_partner_stm_list()),
    }


class BrainRouter:

    def __init__(self):
        self._partner_sessions: dict = {}
        self._user_locks: dict[int, asyncio.Lock] = {}
        self._background_tasks: set[asyncio.Task] = set()

    async def process(self, *args, **kwargs) -> ExecutionResult:
        """Serialize one user's turns so STM order and durable memory stay coherent.

        Discord can deliver overlapping messages (and interactions) from the same
        person.  Processing them concurrently used to let later replies overwrite
        newer memory snapshots. Different users still run fully concurrently.
        """
        user_id = kwargs.get("user_id", args[0] if args else 0)
        lock = self._user_locks.get(user_id)
        if lock is None:
            if len(self._user_locks) > 200:
                # Prune unlocked locks to prevent unbounded growth
                for k in list(self._user_locks.keys()):
                    l = self._user_locks.get(k)
                    if l and not l.locked():
                        self._user_locks.pop(k, None)
            lock = self._user_locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            return await self._process_unlocked(*args, **kwargs)

    async def _process_unlocked(
        self,
        user_id:      int,
        username:     str,
        display_name: str,
        text:         str,
        guild_id:     int  = 0,
        channel_id:   int  = 0,
        is_dm:        bool = False,
        is_mention:   bool = False,
        guild_config        = None,
    ) -> ExecutionResult:

        packet = RoutePacket.create(
            user_id=user_id, username=username, display_name=display_name,
            text=text, guild_id=guild_id, channel_id=channel_id,
            is_dm=is_dm, is_mention=is_mention,
        )
        log.debug(f"[{packet.request_id}] Processing: {username} guild={guild_id}")

        # ── 0. GuildConfig ────────────────────────────────────────────────────
        if guild_config is None and guild_id:
            guild_config = memory_manager.get_guild_config(guild_id)

        memory_allowed       = True
        relationship_allowed = True

        if guild_config and not is_dm:
            if not guild_config.memory_enabled:
                memory_allowed = False
            if guild_config.relationship_mode == "disabled":
                relationship_allowed = False

        # ── 1. Memory load ────────────────────────────────────────────────────
        if not memory_manager.is_memory_available():
            memory_allowed = False

        um = memory_manager.load(user_id, username, display_name)

        # ── 2. Partner DM detection ───────────────────────────────────────────
        is_partner    = aishu_state.is_partner(user_id)
        is_partner_dm = is_partner and is_dm

        # ── 3. Roleplay detection (partner DM only) ───────────────────────────
        rp_exit_response = None

        if is_partner_dm:
            rp  = um.roleplay
            tl  = text.lower()

            # Check END first
            if is_rp_end(text) and rp.is_active:
                rp.end_session()
                um.mark_dirty()
                um.flush()
                rp_exit_response = _rp_exit_message(aishu_state.mood.mood)

            # Check RESUME
            elif is_rp_resume(text):
                resumed = rp.resume_session(0)
                if resumed:
                    um.mark_dirty()
                    um.flush()
                    # Let normal processing handle the response — roleplay is now active
                    log.info(f"[{packet.request_id}] Roleplay resumed: {resumed.role_aishu}")
                else:
                    rp_exit_response = "we haven't done any roleplay yet~ start one? 🌸"

            # Check START (or new RP while one is active = switch)
            elif is_rp_start(text):
                roles = extract_roles(text)
                session = rp.start_session(**roles)
                um.mark_dirty()
                um.flush()
                log.info(
                    f"[{packet.request_id}] Roleplay started: "
                    f"{session.role_aishu} × {session.role_partner}"
                )
                # Let normal processing continue — prompt_engine will inject roleplay context

        # Return early for clean exit responses
        if rp_exit_response:
            return ExecutionResult.ok(
                request_id = packet.request_id,
                chunks     = [rp_exit_response],
                model      = "system",
                latency    = 0.0,
            )

        # ── 4. Reasoning ──────────────────────────────────────────────────────
        reasoning = reasoning_engine.analyze(text)

        # ── 5. Server context ─────────────────────────────────────────────────
        server_topics = memory_manager.get_server_topics(guild_id) if guild_id else []

        # ── 6. Mood boost ─────────────────────────────────────────────────────
        rel_tier = aishu_state.relationships.get_tier(guild_id, user_id)
        aishu_state.mood.apply_relationship_boost(rel_tier)

        # ── 7. Partner memory side selection ─────────────────────────────────
        partner_side = "private"
        if is_partner_dm:
            now     = _time.monotonic()
            session = self._partner_sessions.get(user_id)
            wants_normal = _wants_normal_memory(text)
            if wants_normal:
                partner_side = "normal"
            elif session and (now - session["ts"]) < _PARTNER_SESSION_TIMEOUT:
                partner_side = session["side"]
            self._partner_sessions[user_id] = {"side": partner_side, "ts": now}

        # ── 8. LTM skip decision ──────────────────────────────────────────────
        # During active roleplay — skip normal LTM (roleplay has its own memory)
        is_rp_active = is_partner_dm and um.roleplay.is_active
        skip_ltm = is_rp_active or not memory_optimizer.needs_ltm(
            text, reasoning.intent, is_partner_dm)

        counts = _memory_debug_counts(um)
        log.debug(
            f"[{packet.request_id}] memory-debug user_id={user_id} guild_id={guild_id} "
            f"is_partner_dm={is_partner_dm} partner_side={partner_side} "
            f"intent={reasoning.intent} skip_ltm={skip_ltm} memory_allowed={memory_allowed} "
            f"counts={counts}"
        )

        # ── 9. Build prompt ───────────────────────────────────────────────────
        system_prompt, ctx = prompt_engine.build_system_prompt(
            aishu          = aishu_state,
            um             = um,
            guild_id       = guild_id,
            server_topics  = server_topics,
            current_msg    = text,
            request_id     = packet.request_id,
            is_partner_dm  = is_partner_dm,
            partner_side   = partner_side,
            skip_ltm       = skip_ltm,
        )

        hint = reasoning_engine.build_reasoning_hint(reasoning)
        if hint and not is_rp_active:
            system_prompt += hint

        log.debug(
            f"[{packet.request_id}] ~{ctx.estimated_tokens}tk "
            f"skip_ltm={skip_ltm} partner_dm={is_partner_dm} rp={is_rp_active}"
        )
        log.debug(
            f"[{packet.request_id}] memory-context loaded={bool(ctx.memory_block)} "
            f"shared_included={bool(ctx.server_block)} global_included=False "
            f"memory_block={ctx.memory_block!r} server_block={ctx.server_block!r}"
        )

        # ── 10. Build messages (STM trimmed by roleplay if active) ────────────
        if is_partner_dm and partner_side == "private":
            # get_partner_stm_list() auto-trims to roleplay limit when RP is active
            stm_to_use = um.get_partner_stm_list()
        else:
            stm_to_use = um.get_stm_list()

        messages = prompt_engine.build_messages(
            system_prompt = system_prompt,
            stm           = stm_to_use,
            user_message  = text,
        )
        # Never log message payloads: they contain private Discord conversations.
        log.debug("[%s] assembled %s context messages", packet.request_id, len(messages))

        # ── 11. Call model ────────────────────────────────────────────────────
        loop = asyncio.get_running_loop()
        if is_partner_dm:
            raw_reply, model_used, latency, fail_kind = await loop.run_in_executor(
                None, model_controller.get_reply_partner, messages
            )
        else:
            raw_reply, model_used, latency, fail_kind = await loop.run_in_executor(
                None, model_controller.get_reply, messages
            )

        # ── 12. Handle failure ────────────────────────────────────────────────
        if fail_kind or not raw_reply:
            kind   = fail_kind or FAIL_NO_MODEL
            fb_msg = get_failure_message(kind, aishu_state.mood.mood)
            log.warning(f"[{packet.request_id}] Pipeline failure: {kind}")
            return ExecutionResult.fail(
                request_id      = packet.request_id,
                kind            = kind,
                reason          = f"model_controller returned: {kind}",
                fallback_chunks = [fb_msg],
            )

        # ── 13. Process response ──────────────────────────────────────────────
        chunks = response_engine.process(raw_reply, mood=aishu_state.mood.mood)

        # ── 14. Commit Core state before releasing this user's turn ──────────
        # This is intentionally awaited: it prevents an overlapping turn from
        # building context against stale STM/LTM or losing a just-created memory.
        await self._update_core_state(
            packet               = packet,
            raw_reply            = raw_reply,
            reasoning            = reasoning,
            memory_allowed       = memory_allowed,
            relationship_allowed = relationship_allowed,
            is_partner_dm        = is_partner_dm,
            partner_side         = partner_side,
            is_rp_active         = is_rp_active,
        )

        return ExecutionResult.ok(
            request_id = packet.request_id,
            chunks     = chunks,
            model      = model_used,
            latency    = latency,
        )

    async def _update_core_state(
        self,
        packet:               RoutePacket,
        raw_reply:            str,
        reasoning,
        memory_allowed:       bool = True,
        relationship_allowed: bool = True,
        is_partner_dm:        bool = False,
        partner_side:         str  = "private",
        is_rp_active:         bool = False,
    ):
        try:
            aishu_state.mood.process_message(packet.text, trigger=packet.text[:40])

            if relationship_allowed:
                delta = RelationshipSystem.calculate_delta(
                    text        = packet.text,
                    is_question = reasoning.is_question,
                    sentiment   = reasoning.sentiment,
                )
                aishu_state.relationships.update(
                    packet.guild_id, packet.user_id, packet.username, delta
                )
                aishu_state.check_auto_promote_lover(
                    packet.guild_id, packet.user_id, packet.username
                )

            if memory_allowed:
                if is_partner_dm:
                    if partner_side == "private":
                        memory_manager.record_conversation_partner(
                            packet.user_id, packet.username, packet.display_name,
                            packet.text, raw_reply,
                        )
                    else:
                        memory_manager.record_conversation(
                            packet.user_id, packet.username, packet.display_name,
                            packet.text, raw_reply,
                        )

                    # Roleplay episode memory recording
                    if is_rp_active:
                        um = memory_manager.get(packet.user_id)
                        if um and um.roleplay.is_active:
                            um.roleplay.record_message(packet.text, raw_reply)
                            um.mark_dirty()

                            # Trigger summary update if needed
                            session = um.roleplay.active_session
                            if session and session.needs_summary_update():
                                task = asyncio.create_task(self._update_rp_summary(
                                    packet.user_id, packet.request_id,
                                ))
                                self._background_tasks.add(task)
                                task.add_done_callback(self._background_tasks.discard)
                            um.save(force=False)

                else:
                    memory_manager.record_conversation(
                        packet.user_id, packet.username, packet.display_name,
                        packet.text, raw_reply,
                    )

                # UTM promotion (non-roleplay only — don't pollute normal LTM with RP content)
                if not is_rp_active:
                    candidates = memory_manager.detect_promotion_candidates(packet.user_id)
                    um_ref     = memory_manager.get(packet.user_id)
                    if um_ref and candidates:
                        for c in candidates:
                            um_ref.promote_utm_to_ltm(c, source="promoted")
                            log.debug(f"[{packet.request_id}] UTM→LTM: {c[:50]}")

            if memory_allowed and packet.guild_id and len(packet.text) > 20:
                memory_manager.record_server_topic(packet.guild_id, packet.text[:100])

            aishu_state.mood.drift_toward_neutral()
            aishu_state.save()

        except Exception as e:
            log.error(f"[{packet.request_id}] Core state update error: {e}")

    async def _update_rp_summary(self, user_id: int, request_id: str):
        """
        Regenerate the living session summary every SUMMARY_UPDATE_EVERY messages.
        Uses last 20 partner STM messages to build a compact 2-3 sentence summary.
        Fires as a background task — never blocks the response.
        """
        try:
            um = memory_manager.get(user_id)
            if not um or not um.roleplay.is_active:
                return

            session  = um.roleplay.active_session
            recent   = um.get_partner_stm_list()[-20:]

            if not recent:
                return

            # Build a summary prompt — uses cheapest available model
            convo = "\n".join(
                f"{'partner' if m['role'] == 'user' else 'aishu'}: {m['content']}"
                for m in recent
            )
            summary_system = (
                "You summarize roleplay conversations in 2-3 compact sentences. "
                "Focus on: emotional tone, what happened, how they're relating. "
                "Be concise. No filler words. Present tense."
            )
            summary_messages = [
                {"role": "system",  "content": summary_system},
                {"role": "user",    "content": f"Summarize this roleplay:\n{convo}"},
            ]

            loop = asyncio.get_running_loop()
            reply, _, _, fail = await loop.run_in_executor(
                None, model_controller.get_reply, summary_messages
            )

            if reply and not fail:
                session.session_summary    = reply.strip()[:400]
                session.summary_at_msg     = session.message_count
                um.mark_dirty()
                um.flush()
                log.debug(f"[{request_id}] RP summary updated at msg#{session.message_count}")

        except Exception as e:
            log.error(f"[{request_id}] RP summary update failed: {e}")

    def get_status(self) -> dict:
        return {
            "mood":           aishu_state.mood.mood,
            "mood_score":     aishu_state.mood.score,
            "mood_intensity": aishu_state.mood.intensity,
            "mood_energy":    aishu_state.mood.energy,
            "lover":          aishu_state.lover_name,
            "users_loaded":   memory_manager.user_count(),
            "best_model":     model_controller.best_model(),
            "memory_ok":      memory_manager.is_memory_available(),
        }


def _rp_exit_message(mood: str) -> str:
    messages = {
        "happy":   "okay okay i'm back 😄 that was fun tho ngl~",
        "soft":    "back to being me~ 🥹 that was really nice",
        "playful": "alright i'm out of character lol that was kinda fun tho",
        "excited": "okay i'm me again!! that was SO fun we should do that again 🤩",
        "flirty":  "breaking character~ 😘 did you enjoy that?",
        "shy":     "o-okay back to normal 🥺 that was... kinda fun",
        "neutral": "okay, roleplay ended. back to normal 🌸",
        "bored":   "okay fine, done. that was actually kinda fun tbh",
        "annoyed": "okay we're done. back to normal.",
        "sad":     "back to being me... 😔 that was nice while it lasted",
        "angry":   "fine. done. back to normal.",
    }
    return messages.get(mood, "okay i'm back 😄 that was fun~")


# Global singleton
brain_router = BrainRouter()
