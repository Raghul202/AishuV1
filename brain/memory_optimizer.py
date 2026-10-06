"""
brain/memory_optimizer.py — Token-budget-aware memory context selection.

Reads from Core memory — never writes.
Selects the most relevant memories for each API call within a token budget.
"""

import re

from core.memory.user_memory import UserMemory
from utilities.logger import get_logger

log = get_logger("brain.memory_optimizer")

MAX_FACTS_IN_PROMPT   = 5
MAX_PREFS_IN_PROMPT   = 4
MAX_TOPICS_IN_PROMPT  = 3
MAX_UTM_IN_PROMPT     = 3

# Rough token estimate per character
CHARS_PER_TOKEN = 4
DEFAULT_TOKEN_BUDGET = 600  # characters budget for memory section
_WORD_RE = re.compile(r"[\w']+", re.UNICODE)
_STOP_WORDS = frozenset({"a", "an", "and", "are", "as", "at", "be", "but", "for", "from", "i", "in", "is", "it", "me", "my", "of", "on", "or", "the", "that", "this", "to", "was", "we", "with", "you", "your"})


class MemoryOptimizer:
    """
    Prepares optimized memory context for a single API call.
    Read-only access to Core memory.
    """

    def build_context(self, um: UserMemory, current_msg: str = "",
                      token_budget: int = DEFAULT_TOKEN_BUDGET,
                      request_id: str = "") -> str:
        """
        Build the memory context string for a user.
        Uses relevance ranking if current_msg is provided,
        falls back to importance-sorted selection otherwise.
        """
        rid = request_id or "?"

        if not um.has_long_term_memory() and not um.utm:
            log.debug(f"[{rid}] build_context() -> empty (no LTM/UTM available)")
            return ""

        # Get relevant memories if we have a message to match against
        if current_msg:
            facts  = self._select_relevant(um._ltm_facts, current_msg, MAX_FACTS_IN_PROMPT)
            prefs  = self._select_relevant(um._ltm_prefs, current_msg, MAX_PREFS_IN_PROMPT)
            topics = self._select_relevant(um._ltm_topics, current_msg, MAX_TOPICS_IN_PROMPT)
        else:
            facts  = self._top_by_importance(um._ltm_facts, MAX_FACTS_IN_PROMPT)
            prefs  = self._top_by_importance(um._ltm_prefs, MAX_PREFS_IN_PROMPT)
            topics = self._top_by_importance(um._ltm_topics, MAX_TOPICS_IN_PROMPT)

        utm_recent = um.utm[-MAX_UTM_IN_PROMPT:]

        parts = []
        if facts:
            parts.append("facts: " + " | ".join(facts))
        if prefs:
            parts.append("prefs: " + " | ".join(prefs))
        if topics:
            parts.append("topics: " + " | ".join(topics))
        if utm_recent:
            parts.append("recent: " + " | ".join(utm_recent))

        if not parts:
            return ""

        full = self._fit_budget(parts, token_budget, rid)

        log.debug(
            f"[{rid}] build_context() facts={len(facts)} prefs={len(prefs)} "
            f"topics={len(topics)} utm={len(utm_recent)} -> {full!r}"
        )
        return full

    def _select_relevant(self, items: list, current_msg: str, limit: int) -> list:
        """
        Select items by keyword relevance to the current message.
        Falls back to importance order if no matches.
        """
        if not items:
            return []

        words = self._keywords(current_msg)
        scored = []
        for position, item in enumerate(items):
            content   = item.content if hasattr(item, 'content') else str(item)
            item_words = self._keywords(content)
            overlap    = len(words & item_words)
            importance = item.importance if hasattr(item, 'importance') else 5
            mentions = min(getattr(item, 'mention_count', 1), 8)
            confidence = getattr(item, 'confidence', .7)
            # Exact topical overlap dominates, while durable and repeatedly confirmed
            # memories remain useful when the current message is ambiguous.
            score = overlap * 12 + importance * 1.6 + mentions * .45 + confidence + position / max(len(items), 1)
            scored.append((score, content))

        scored.sort(reverse=True)
        return [c for _, c in scored[:limit]]

    @staticmethod
    def _keywords(text: str) -> set[str]:
        return {word for word in _WORD_RE.findall(text.casefold())
                if len(word) > 2 and word not in _STOP_WORDS}

    @staticmethod
    def _fit_budget(parts: list[str], token_budget: int, request_id: str) -> str:
        cap = max(80, token_budget * CHARS_PER_TOKEN)
        selected: list[str] = []
        used = len("[memory] ")
        for part in parts:
            separator = 4 if selected else 0
            if used + separator + len(part) <= cap:
                selected.append(part)
                used += separator + len(part)
        if not selected:
            # Keep the most useful first section intact as far as possible rather
            # than cutting arbitrary memory text in the middle.
            selected.append(parts[0][: max(1, cap - len("[memory] "))].rstrip())
        full = "[memory] " + " // ".join(selected)
        if len(selected) < len(parts):
            log.debug(f"[{request_id}] memory selection constrained to {token_budget} tokens")
        return full

    def _top_by_importance(self, items: list, limit: int) -> list:
        """Select items by importance score."""
        if not items:
            return []
        sorted_items = sorted(items,
                               key=lambda m: (getattr(m, 'importance', 5),
                                              getattr(m, 'mention_count', 1)),
                               reverse=True)
        return [m.content if hasattr(m, 'content') else str(m)
                for m in sorted_items[:limit]]

    def build_summary(self, um: UserMemory) -> str:
        """Very compact summary for extremely token-tight situations."""
        snippets = []
        if um._ltm_facts:
            snippets.append(um._ltm_facts[-1].content)
        if um._ltm_prefs:
            snippets.append(um._ltm_prefs[-1].content)
        return ("Quick context: " + "; ".join(snippets)) if snippets else ""

    def build_context_partner(self, um: UserMemory, current_msg: str = "",
                               token_budget: int = 700,
                               request_id: str = "") -> str:
        """
        Build memory context for partner DM sessions.
        Includes both normal LTM and partner-private LTM.
        Partner-private memories are shown first as they are more intimate/relevant.
        Normal chat never calls this method — isolation is guaranteed by the router.
        """
        rid = request_id or "?"
        parts = []

        # Partner-private LTM (higher priority — shown first)
        p_facts  = self._select_relevant(um._partner_ltm_facts, current_msg, MAX_FACTS_IN_PROMPT) \
                   if current_msg else self._top_by_importance(um._partner_ltm_facts, MAX_FACTS_IN_PROMPT)
        p_prefs  = self._select_relevant(um._partner_ltm_prefs, current_msg, MAX_PREFS_IN_PROMPT) \
                   if current_msg else self._top_by_importance(um._partner_ltm_prefs, MAX_PREFS_IN_PROMPT)

        if p_facts:
            parts.append("private facts: " + " | ".join(p_facts))
        if p_prefs:
            parts.append("private prefs: " + " | ".join(p_prefs))

        # Normal LTM (general context)
        if current_msg:
            facts  = self._select_relevant(um._ltm_facts,  current_msg, MAX_FACTS_IN_PROMPT)
            prefs  = self._select_relevant(um._ltm_prefs,  current_msg, MAX_PREFS_IN_PROMPT)
            topics = self._select_relevant(um._ltm_topics, current_msg, MAX_TOPICS_IN_PROMPT)
        else:
            facts  = self._top_by_importance(um._ltm_facts,  MAX_FACTS_IN_PROMPT)
            prefs  = self._top_by_importance(um._ltm_prefs,  MAX_PREFS_IN_PROMPT)
            topics = self._top_by_importance(um._ltm_topics, MAX_TOPICS_IN_PROMPT)

        if facts:
            parts.append("facts: " + " | ".join(facts))
        if prefs:
            parts.append("prefs: " + " | ".join(prefs))
        if topics:
            parts.append("topics: " + " | ".join(topics))

        utm_recent = um.utm[-MAX_UTM_IN_PROMPT:]
        if utm_recent:
            parts.append("recent: " + " | ".join(utm_recent))

        if not parts:
            log.debug(f"[{rid}] build_context_partner() -> empty (no partner/normal memory selected)")
            return ""

        full = self._fit_budget(parts, token_budget, rid)
        log.debug(
            f"[{rid}] build_context_partner() private_facts={len(p_facts)} "
            f"private_prefs={len(p_prefs)} facts={len(facts)} prefs={len(prefs)} "
            f"topics={len(topics)} utm={len(utm_recent)} -> {full!r}"
        )
        return full

    @staticmethod
    def needs_ltm(text: str, intent: str, is_partner_dm: bool = False) -> bool:
        """
        Decide whether LTM retrieval is needed for this request.
        Lightweight heuristic on text content + reasoning intent.

        Skips LTM for:
          - pure filler / very short reactions
          - common greetings, affection lines, reactions with no recall signal
          - short partner DM messages with no recall signal

        Always loads LTM for:
          - memory/recall/preference questions
          - past-event references
          - identity/personal-detail questions
          - emotional messages (intent-based)
        """
        # Keywords that strongly signal LTM is needed
        _LTM_TRIGGERS = (
            "remember", "recall", "told you", "did you know", "did we",
            "what did", "what do you know", "what do you remember",
            "yesterday", "last time", "before", "earlier", "history",
            "my favorite", "my favourite", "what's my", "what is my",
            "my name", "my project", "my work", "remind me",
            "did i tell", "i told you", "you said", "you told me",
            "did you forget", "you remember", "do you remember",
        )

        tl = text.lower().strip()

        # Always load when a clear recall signal is present
        if any(t in tl for t in _LTM_TRIGGERS):
            return True

        # Always load for questions — likely seeking remembered information
        if intent == "question":
            return True

        # Always load for emotional messages — context helps empathetic replies
        if intent == "emotional":
            return True

        # Skip for pure filler or very short messages
        if intent == "filler" or len(tl) <= 12:
            return False

        # Skip common short affection / greeting lines with no recall signal
        _NO_LTM_EXACT = {
            "hi", "hey", "hello", "hii", "hiyaa", "heyy",
            "good night", "gn", "goodnight", "good morning", "gm",
            "missed you", "miss you", "missed me", "i miss you",
            "come here", "hey baby", "hey babe", "morning", "night",
            "ok", "okay", "hmm", "haha", "lol", "lmao", "hehe",
            "bye", "cya", "see you", "talk later", "brb",
        }
        if tl in _NO_LTM_EXACT:
            return False

        # Partner DM without a recall signal — skip LTM for short messages
        if is_partner_dm and len(tl) < 30:
            return False

        # Default: load LTM
        return True

    def detect_promotion_candidates(self, um: UserMemory) -> list:
        """
        Find UTM entries that appear frequently in recent STM.
        These are candidates for promotion to LTM.
        """
        from config.settings import UTM_PROMOTION_HITS
        candidates = []
        stm_text   = " ".join(
            m["content"].lower() for m in um.get_stm_list() if m["role"] == "user"
        )
        for entry in um.utm:
            words     = [w for w in entry.lower().split() if len(w) > 4]
            hit_count = sum(stm_text.count(w) for w in words)
            if hit_count >= UTM_PROMOTION_HITS:
                candidates.append(entry)
        return candidates


# Global singleton
memory_optimizer = MemoryOptimizer()
