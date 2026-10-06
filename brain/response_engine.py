"""
brain/response_engine.py — Response formatting and output polishing.

Takes raw AI model output and:
  - Removes artifacts (markdown, formatting noise)
  - Adjusts tone to match current mood
  - Ensures consistency with Aishu's personality
  - Prepares Discord-ready message splits
"""

import re
from utilities.helpers import split_naturally, SAFE_LIMIT
from utilities.logger import get_logger

log = get_logger("brain.response_engine")

# Phrases that sound too bot-like — Aishu should never say these
_BOT_PHRASES = [
    r"as an ai\b",
    r"i'm an ai\b",
    r"i am an ai\b",
    r"i'm a (language )?model\b",
    r"i cannot feel\b",
    r"i don't have feelings\b",
    r"i'd be happy to help\b",
    r"how can i assist\b",
    r"certainly[,!]?\s",
    r"absolutely[,!]?\s",
    r"of course[,!]?\s",
    r"i understand that you\b",
    r"as a (helpful )?assistant\b",
]
_BOT_RE = re.compile("|".join(_BOT_PHRASES), re.IGNORECASE)
_REASONING_LEAK_RE = re.compile(
    r"(?:^|\n)\s*(?:we are in (?:a |the )?(?:dm|server) context|"
    r"according to (?:the )?(?:state|instructions)|we should(?: not)?|"
    r"let'?s think|options:|example:|the user said|to respond as aishu)",
    re.IGNORECASE,
)

# Replacements for common bot phrases
_REPLACEMENTS = {
    r"certainly,?\s+": "",
    r"absolutely,?\s+": "",
    r"of course,?\s+": "",
    r"sure thing,?\s+": "",
    r"i understand that ": "yeah ",
    r"feel free to ": "you can ",
}

# Max length for a single Discord message — use the safe limit from helpers
_MAX_DISCORD_LEN = SAFE_LIMIT


class ResponseEngine:
    """
    Cleans and formats AI responses before they reach the user.
    Ensures Aishu always sounds like herself, not a chatbot.
    """

    def process(self, raw: str, mood: str = "neutral") -> list[str]:
        """
        Full pipeline:
          1. Clean formatting artifacts
          2. Remove bot-like phrases
          3. Apply mood-based micro-adjustments
          4. Split into natural Discord-sized chunks

        Returns a list of strings (message chunks to send in order).
        """
        if not raw or not raw.strip():
            return self._fallback(mood)

        text = raw.strip()
        # Some reasoning-capable providers occasionally place their hidden
        # scratchpad in `content`. Never expose prompt/state analysis to users.
        if _REASONING_LEAK_RE.search(text):
            log.warning("Discarded provider reasoning leaked into response content")
            return self._fallback(mood)
        text = self._clean_formatting(text)
        text = self._remove_bot_phrases(text)
        text = self._apply_replacements(text)
        text = self._apply_mood_touch(text, mood)
        text = text.strip()

        if not text:
            return self._fallback(mood)

        chunks = split_naturally(text, max_chunk=_MAX_DISCORD_LEN)
        log.debug(f"Response processed: {len(raw)} chars → {len(chunks)} chunk(s)")
        return chunks

    def _clean_formatting(self, text: str) -> str:
        """Remove markdown artifacts that look weird in Discord messages."""
        # Remove excessive headers (##, ###)
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        # Remove bold/italic markdown (Aishu can use them, but not blocks)
        # Keep single * for italic, remove ** blocks used structurally
        text = re.sub(r"\*{3}(.+?)\*{3}", r"\1", text, flags=re.DOTALL)
        # Remove horizontal rules
        text = re.sub(r"^[-_*]{3,}\s*$", "", text, flags=re.MULTILINE)
        # Remove code blocks (replace with content only)
        text = re.sub(r"```[\w]*\n?(.*?)```", r"\1", text, flags=re.DOTALL)
        # Clean up excessive newlines
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Clean trailing whitespace per line
        text = "\n".join(line.rstrip() for line in text.splitlines())
        return text

    def _remove_bot_phrases(self, text: str) -> str:
        """Remove phrases that break Aishu's character while preserving line structure."""
        if _BOT_RE.search(text):
            log.debug("Bot phrase detected — cleaning response")
            lines = text.splitlines()
            cleaned_lines = []
            for line in lines:
                if not line.strip():
                    cleaned_lines.append("")
                    continue
                sentences = re.split(r"(?<=[.!?])\s+", line)
                clean_sents = [s for s in sentences if not _BOT_RE.search(s)]
                if clean_sents:
                    cleaned_lines.append(" ".join(clean_sents))
            text = "\n".join(cleaned_lines)
        return text

    def _apply_replacements(self, text: str) -> str:
        """Apply string replacements to improve naturalness."""
        for pattern, replacement in _REPLACEMENTS.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text

    def _apply_mood_touch(self, text: str, mood: str) -> str:
        """
        Apply very light mood-based adjustments.
        This is subtle — the AI already has the mood in its prompt.
        This is just a safety pass to catch any tone mismatches.
        """
        # If mood is annoyed/angry and response is very long — trim it
        if mood in ("annoyed", "angry") and len(text) > 400:
            # Try to keep first 2 sentences only
            sentences = re.split(r"(?<=[.!?])\s+", text)
            if len(sentences) > 3:
                text = " ".join(sentences[:2]).strip()
                log.debug(f"Trimmed response for mood={mood}")

        # If mood is sad and response sounds overly cheerful — leave it
        # (the AI should handle this via the prompt; we don't force-alter tone here)

        return text

    def _fallback(self, mood: str) -> list[str]:
        """Return a mood-appropriate fallback when response is unusable."""
        fallbacks = {
            "excited": ["wait hold on— something went wrong on my end 😅 try again?"],
            "flirty":  ["hey wait something broke~ say that again? 😘"],
            "happy":   ["hmm, i blanked for a sec 😅 say that again?"],
            "soft":    ["oh... something went wrong 🥹 try again?"],
            "playful": ["okay that's weird, my brain glitched lol. again?"],
            "neutral": ["sorry, something went wrong... try again?"],
            "shy":     ["s-sorry something went wrong 🥺 try again?"],
            "bored":   ["eh, failed. try again i guess"],
            "annoyed": ["ugh it broke. try later."],
            "sad":     ["sorry... something went wrong 😔"],
            "angry":   ["not working right now."],
        }
        return fallbacks.get(mood, ["something went wrong, try again? 😅"])

    def format_for_discord(self, text: str) -> str:
        """Ensure a single message is within Discord's character limit.
        If it exceeds the safe limit, returns the first chunk only — use
        split_naturally() directly when you need all chunks."""
        if len(text) <= _MAX_DISCORD_LEN:
            return text
        chunks = split_naturally(text, max_chunk=_MAX_DISCORD_LEN)
        return chunks[0] if chunks else text


# Global singleton
response_engine = ResponseEngine()
