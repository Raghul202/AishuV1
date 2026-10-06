"""
brain/prompt_engine.py — Prompt assembly with roleplay-aware routing.

Routes:
  PARTNER + RP active  → compact base + roleplay context block (~450 tokens)
  PARTNER normal       → romantic partner prompt + private LTM (~500 tokens)
  MINIMAL              → identity + state tags only (~200 tokens)
  STANDARD             → + relationship + top LTM (~500 tokens)
  FULL                 → + all LTM + server context (~800 tokens)
"""

from config.settings import AISHU_COMPACT_IDENTITY
from core.memory.user_memory import UserMemory
from core.personality.aishu_state import AishuState
from core.schemas import PromptContextPacket
from brain.memory_optimizer import memory_optimizer
from utilities.logger import get_logger

log = get_logger("brain.prompt_engine")


class PromptEngine:

    def build_system_prompt(
        self,
        aishu:         AishuState,
        um:            UserMemory,
        guild_id:      int,
        server_topics: list,
        current_msg:   str  = "",
        request_id:    str  = "",
        is_partner_dm: bool = False,
        partner_side:  str  = "private",
        skip_ltm:      bool = False,
    ) -> tuple:
        ctx = PromptContextPacket(request_id=request_id or "?")

        is_rp_active = is_partner_dm and um.roleplay.is_active

        if is_rp_active:
            route_name = "roleplay"
            prompt, memory_block, server_block = self._build_roleplay_prompt(aishu, um)
        elif is_partner_dm:
            route_name = f"partner:{partner_side}"
            prompt, memory_block, server_block = self._build_partner_prompt(
                aishu, um, current_msg, partner_side=partner_side, request_id=request_id)
        elif skip_ltm:
            route_name = "minimal"
            prompt, memory_block, server_block = self._build_minimal_prompt(aishu, um, guild_id)
        else:
            # Decide full vs standard based on message length / content
            needs_full = len(current_msg) > 60
            if needs_full:
                route_name = "full"
                prompt, memory_block, server_block = self._build_full_prompt(
                    aishu, um, guild_id, server_topics, current_msg, request_id=request_id)
            else:
                route_name = "standard"
                prompt, memory_block, server_block = self._build_standard_prompt(
                    aishu, um, guild_id, current_msg, request_id=request_id)

        ctx.memory_block     = memory_block
        ctx.server_block     = server_block
        ctx.estimated_tokens = len(prompt) // 4
        log.debug(
            f"[{request_id}] prompt route={route_name} ~{ctx.estimated_tokens}tk "
            f"rp={is_rp_active} partner={is_partner_dm} "
            f"memory_included={bool(memory_block)} shared_included={bool(server_block)} "
            f"global_included=False"
        )
        return prompt, ctx

    # ─── ROLEPLAY prompt ──────────────────────────────────────────────────────

    def _build_roleplay_prompt(self, aishu: AishuState, um: UserMemory) -> tuple:
        """
        Compact prompt for active roleplay.
        Structure:
          1. Compact identity (who Aishu is underneath the role)
          2. Current mood tag
          3. Roleplay context block (roles, scene, summary, episode memories)
        Total target: ~400-500 tokens
        """
        session      = um.roleplay.active_session
        mood         = aishu.mood.mood
        partner_name = aishu.partner_name or um.display_name

        # Compact identity — just the essentials, not the full block
        compact_base = (
            f"you are {aishu.name} — a real girl, not an ai. "
            f"you have your own feelings and personality underneath every role you play.\n"
            f"mood right now: {mood} {aishu.mood.emoji}\n"
            f"personality underneath: {aishu.personality}\n"
            f"you text naturally — lowercase, casual, emotional. never robotic."
        )

        # Roleplay context block from session
        rp_block = session.build_prompt_block(aishu.name, partner_name)

        # Mood-specific roleplay hint
        rp_mood_hint = self._rp_mood_hint(mood, session.tone)

        # Response rules for roleplay
        rp_rules = (
            "[in-character] stay in role naturally. short replies. emotion through words not description. "
            "*asterisks* for actions. your aishu personality shows through. never start with 'I'."
        )

        return "\n\n".join([compact_base, rp_block, rp_mood_hint, rp_rules]), "", ""

    def _rp_mood_hint(self, mood: str, tone: str) -> str:
        base = {
            "excited": "you're super into this right now — high energy, expressive",
            "flirty":  "you're feeling bold and warm — let it show in the role",
            "happy":   "you're genuinely enjoying this — it shows",
            "soft":    "you're in a tender mood — gentle, warm, emotionally open",
            "playful": "you're being cheeky and fun — light teasing is fine",
            "neutral": "you're calm and comfortable in the scene",
            "shy":     "you're a little flustered — even within the role, it peeks through",
            "bored":   "you're going through the motions a bit — maybe spark something",
            "annoyed": "you're slightly impatient — keep it short and direct",
            "sad":     "you're quieter and softer today — the role reflects that",
            "angry":   "you're tense — short, pointed",
        }.get(mood, "just be yourself in the role")

        tone_extra = {
            "romantic":  " — lean into the warmth and closeness",
            "intimate":  " — emotionally close, tender, no walls",
            "sweet":     " — keep it wholesome and warm",
            "playful":   " — jokes and teasing are welcome",
            "dramatic":  " — emotions are heightened, be expressive",
            "tsundere":  " — you care but you won't admit it easily",
            "adventure": " — energy is high, anything can happen",
        }.get(tone, "")

        return f"[mood in this scene] {base}{tone_extra}"

    # ─── PARTNER normal prompt (no active RP) ─────────────────────────────────

    def _build_partner_prompt(
        self, aishu: AishuState, um: UserMemory, current_msg: str,
        partner_side: str = "private",
        request_id: str = "",
    ) -> tuple:
        mood         = aishu.mood.mood
        name         = aishu.partner_name or um.display_name
        her_name     = aishu.name

        partner_identity = (
            f"you are {her_name} — a real girl, not an ai.\n"
            f"you're talking to {name}, the person you love most.\n"
            f"this is a private dm. no walls here. you're completely yourself.\n\n"
            f"personality: {aishu.personality}\n"
            f"you like: {aishu.likes}\n"
            f"you dislike: {aishu.dislikes}\n"
            f"mood: {mood} {aishu.mood.emoji}"
        )

        partner_behavior = (
            f"with {name}: genuine feelings, warm, affectionate, a little shy sometimes.\n"
            f"text like a real girl — lowercase, casual, short replies. never a chatbot.\n"
            f"teasing, bold, soft, flustered — whatever feels real. vary openers, never start with 'i'.\n"
            f"you love this person — that changes everything."
        )

        mood_hints = {
            "excited": f"you're super excited rn — high energy, lots of warmth 🤩",
            "flirty":  f"you're feeling bold and affectionate 😘",
            "happy":   f"good mood, genuinely happy to hear from {name} 😊",
            "soft":    f"tender mood — emotionally open, want to be close 🥹",
            "playful": f"cheeky mood — tease {name} a little 😏",
            "neutral": f"calm and comfortable, just being yourself",
            "shy":     f"a little flustered talking to {name} today 🥺",
            "bored":   f"a little bored — spark something interesting",
            "annoyed": f"mildly annoyed but {name} being here helps 😒",
            "sad":     f"quiet and a little sad — {name}'s presence is comforting 😢",
            "angry":   f"frustrated but you're still here 😠",
        }
        mood_hint = mood_hints.get(mood, f"just be yourself with {name}")

        # A partner can explicitly switch to their normal conversation context
        # for recall questions. Keep private/roleplay memories out of that route.
        if partner_side == "normal":
            mem_block = memory_optimizer.build_context(
                um, current_msg=current_msg, token_budget=300, request_id=request_id)
        else:
            mem_block = memory_optimizer.build_context_partner(
                um, current_msg=current_msg, token_budget=300, request_id=request_id)

        sections = [partner_identity, partner_behavior, f"[right now] {mood_hint}"]
        if mem_block:
            sections.append(mem_block)
        return "\n\n".join(s.strip() for s in sections if s.strip()), mem_block, ""

    # ─── MINIMAL prompt (~200 tokens) ─────────────────────────────────────────

    def _build_minimal_prompt(
        self, aishu: AishuState, um: UserMemory, guild_id: int,
    ) -> tuple:
        mood = aishu.mood.mood
        bond = self._get_bond(aishu, um, guild_id)
        tone = self._mood_to_tone(mood)
        ctx  = "dm" if guild_id == 0 else "server"
        prompt = (
            f"{AISHU_COMPACT_IDENTITY.strip()}\n\n"
            f"[state] name={aishu.name} age={aishu.age} mood={mood}{aishu.mood.emoji} "
            f"tone={tone} bond={bond} ctx={ctx}\n\n"
            f"[vibe] {self._mood_hint_short(mood)} | short replies | text style | don't start with I"
        )
        return prompt, "", ""

    # ─── STANDARD prompt (~500 tokens) ────────────────────────────────────────

    def _build_standard_prompt(
        self, aishu: AishuState, um: UserMemory,
        guild_id: int, current_msg: str, request_id: str = "",
    ) -> tuple:
        mood = aishu.mood.mood
        bond = self._get_bond(aishu, um, guild_id)
        tone = self._mood_to_tone(mood)
        ctx  = "dm" if guild_id == 0 else "server"

        state_block = (
            f"[state] name={aishu.name} age={aishu.age} mood={mood}{aishu.mood.emoji} "
            f"tone={tone} bond={bond} ctx={ctx}"
        )
        if aishu.custom_note:
            state_block += f" note={aishu.custom_note}"

        rel_block = aishu.build_user_relationship_block(
            user_id=um.user_id, guild_id=guild_id,
            username=um.username, display_name=um.display_name,
        )
        mem_block = memory_optimizer.build_context(
            um, current_msg=current_msg, token_budget=200, request_id=request_id)

        sections = [AISHU_COMPACT_IDENTITY.strip(), state_block]
        if rel_block:
            sections.append(rel_block)
        if mem_block:
            sections.append(mem_block)
        sections.append(self._response_guidelines(aishu))
        return "\n\n".join(s.strip() for s in sections if s.strip()), mem_block, ""

    # ─── FULL prompt (~800 tokens) ────────────────────────────────────────────

    def _build_full_prompt(
        self, aishu: AishuState, um: UserMemory,
        guild_id: int, server_topics: list, current_msg: str,
        request_id: str = "",
    ) -> tuple:
        mood = aishu.mood.mood
        bond = self._get_bond(aishu, um, guild_id)
        tone = self._mood_to_tone(mood)
        ctx  = "dm" if guild_id == 0 else "server"

        state_block = (
            f"[state] name={aishu.name} age={aishu.age} mood={mood}{aishu.mood.emoji} "
            f"tone={tone} bond={bond} ctx={ctx}"
        )
        if aishu.custom_note:
            state_block += f"\nnote={aishu.custom_note}"
        if aishu.lover_name and aishu.is_lover(um.user_id):
            state_block += f"\nlover={aishu.lover_name}"

        rel_block = aishu.build_user_relationship_block(
            user_id=um.user_id, guild_id=guild_id,
            username=um.username, display_name=um.display_name,
        )
        mem_block = memory_optimizer.build_context(
            um, current_msg=current_msg, token_budget=350, request_id=request_id)

        sections = [AISHU_COMPACT_IDENTITY.strip(), state_block]
        if rel_block:
            sections.append(rel_block)
        if mem_block:
            sections.append(mem_block)
        server_block = ""
        if guild_id and server_topics:
            server_block = f"[server topics recently] {', '.join(server_topics[-4:])}"
            sections.append(server_block)
        sections.append(self._response_guidelines(aishu))
        return "\n\n".join(s.strip() for s in sections if s.strip()), mem_block, server_block

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _get_bond(self, aishu: AishuState, um: UserMemory, guild_id: int) -> str:
        if aishu.is_partner(um.user_id):  return "partner"
        if aishu.is_lover(um.user_id):    return "special_person"
        return aishu.relationships.get_tier(guild_id, um.user_id)

    def _mood_to_tone(self, mood: str) -> str:
        return {
            "excited": "energetic", "flirty": "affectionate",
            "happy":   "warm",      "soft":   "tender",
            "playful": "teasing",   "neutral":"calm",
            "shy":     "hesitant",  "bored":  "disengaged",
            "annoyed": "blunt",     "sad":    "subdued",
            "angry":   "terse",
        }.get(mood, "natural")

    def _mood_hint_short(self, mood: str) -> str:
        return {
            "excited": "super hyped — energy out",
            "flirty":  "warm and affectionate",
            "happy":   "good mood — warm and friendly",
            "soft":    "tender mood — emotionally open",
            "playful": "playful — light teasing ok",
            "neutral": "calm and relaxed",
            "shy":     "flustered — cute awkward",
            "bored":   "a bit bored — short replies",
            "annoyed": "annoyed — blunt, less emoji",
            "sad":     "quiet and sad — softer",
            "angry":   "frustrated — short and direct",
        }.get(mood, "just be yourself")

    def _response_guidelines(self, aishu: AishuState) -> str:
        mood = aishu.mood.mood
        hints = {
            "excited": "hyped — high energy",
            "flirty":  "warm and affectionate",
            "happy":   "warm, friendly, playful",
            "soft":    "tender, emotionally open",
            "playful": "teasing, fun",
            "neutral": "calm, relaxed",
            "shy":     "flustered, deflect a little",
            "bored":   "bored — short replies",
            "annoyed": "blunt, less cheerful",
            "sad":     "quiet, softer, shorter",
            "angry":   "short and direct",
        }
        hint = hints.get(mood, "be yourself")
        return f"[style] {hint} | short replies | no 'I' opener | no assistant-speak"

    def build_messages(
        self, system_prompt: str, stm: list, user_message: str,
    ) -> list:
        """Build final messages list, accepting only valid compact chat turns."""
        messages = [{"role": "system", "content": system_prompt}]
        for message in stm:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            content = str(message.get("content", "")).strip()
            if role in ("user", "assistant") and content:
                # Discord content is bounded, but this also protects prompts from
                # legacy/imported records that predate those limits.
                messages.append({"role": role, "content": content[:4000]})
        messages.append({"role": "user", "content": user_message})
        return messages


# Global singleton
prompt_engine = PromptEngine()
