"""
brain/reasoning.py — Intent analysis and reasoning module.
Unchanged from v2 — this was already solid.
"""

import re
from dataclasses import dataclass, field
from utilities.helpers import is_question, is_filler
from utilities.logger import get_logger

log = get_logger("brain.reasoning")

POSITIVE_KEYWORDS = {
    "love", "like", "cute", "pretty", "nice", "great", "amazing", "awesome",
    "thanks", "thank", "happy", "fun", "good", "cool", "miss", "care", "kind",
    "sweet", "wonderful", "beautiful", "brilliant", "smart", "funny", "proud",
}
NEGATIVE_KEYWORDS = {
    "hate", "stupid", "dumb", "ugly", "boring", "awful", "terrible", "horrible",
    "useless", "annoying", "shut up", "go away", "idiot", "worst", "bad",
    "rude", "mean", "lame", "pathetic", "worthless",
}
EMOTIONAL_KEYWORDS = {
    "sad", "cry", "crying", "hurt", "broken", "alone", "lonely", "depressed",
    "anxious", "scared", "afraid", "nervous", "panic", "stressed", "overwhelmed",
    "hopeless", "lost", "confused", "miss you", "heartbreak",
}
AGGRESSIVE_KEYWORDS = {
    "stupid bot", "shut up", "go away", "i hate you", "you're useless",
    "dumb ai", "delete yourself", "you suck",
}


@dataclass
class ReasoningResult:
    intent:           str  = "chat"
    sentiment:        str  = "neutral"
    emotion_detected: str  = ""
    response_style:   str  = "normal"
    is_question:      bool = False
    is_filler:        bool = False
    is_aggressive:    bool = False
    emotional_load:   int  = 0
    keywords_found:   list = field(default_factory=list)


class ReasoningEngine:
    def analyze(self, text: str) -> ReasoningResult:
        result = ReasoningResult()
        tl     = text.lower().strip()
        words  = set(re.findall(r"\b\w+\b", tl))

        result.is_filler   = is_filler(text)
        result.is_question = is_question(text)

        pos_hits = words & POSITIVE_KEYWORDS
        neg_hits = words & NEGATIVE_KEYWORDS

        for phrase in AGGRESSIVE_KEYWORDS:
            if phrase in tl:
                result.is_aggressive = True
                neg_hits.add(phrase)

        if pos_hits and not neg_hits:
            result.sentiment = "positive"
        elif neg_hits and not pos_hits:
            result.sentiment = "negative"
        elif pos_hits and neg_hits:
            result.sentiment = "mixed"
        else:
            result.sentiment = "neutral"

        result.keywords_found = list(pos_hits | neg_hits)

        emo_hits = words & EMOTIONAL_KEYWORDS
        for phrase in ["i feel so", "i'm so", "i can't stop", "i'm really"]:
            if phrase in tl:
                emo_hits.add(phrase)

        if emo_hits:
            result.emotional_load = min(10, len(emo_hits) * 3)
            if result.emotional_load >= 3:
                result.emotion_detected = self._classify_emotion(tl, emo_hits)

        if result.is_aggressive:
            result.intent = "aggressive"
        elif (result.emotion_detected and result.sentiment != "positive"):
            result.intent = "emotional"
        elif result.is_question:
            result.intent = "question"
        elif result.is_filler:
            result.intent = "filler"
        else:
            result.intent = "chat"

        result.response_style = self._determine_style(result)
        log.debug(f"Reasoning: intent={result.intent} sentiment={result.sentiment} "
                  f"emotion={result.emotion_detected}")
        return result

    def _classify_emotion(self, text: str, hits: set) -> str:
        if any(w in hits for w in {"sad", "cry", "crying", "heartbreak"}): return "sadness"
        if any(w in hits for w in {"alone", "lonely"}):                    return "loneliness"
        if any(w in hits for w in {"scared", "afraid", "nervous", "anxious", "panic"}): return "anxiety"
        if any(w in hits for w in {"stressed", "overwhelmed"}):            return "stress"
        if any(w in hits for w in {"hurt", "broken", "hopeless"}):         return "pain"
        if "confused" in hits or "lost" in hits:                           return "confusion"
        # Conversational intensifiers ("I'm so", "I feel so") are not
        # emotions by themselves.  Do not turn happy excitement into distress.
        if any(word in text for word in POSITIVE_KEYWORDS):
            return "joy"
        return ""

    def _determine_style(self, result: ReasoningResult) -> str:
        if result.is_aggressive:        return "blunt"
        if result.emotional_load >= 6:  return "supportive"
        if result.emotional_load >= 3:  return "gentle"
        if result.sentiment == "positive": return "playful"
        if result.is_filler:            return "brief"
        return "normal"

    def build_reasoning_hint(self, result: ReasoningResult) -> str:
        if result.intent == "aggressive":
            return ("\n[Response hint: They're being rude. Stand your ground — "
                    "don't just take it. Be assertive but not aggressive back. Short.]")
        if result.intent == "emotional" and result.emotion_detected:
            return (f"\n[Response hint: They seem to be feeling {result.emotion_detected}. "
                    f"Be present. Don't immediately give advice — just be there. Warm, gentle.]")
        if result.response_style == "supportive":
            return ("\n[Response hint: They need support. Be soft, caring, present. "
                    "Don't rush to fix anything.]")
        if result.sentiment == "positive":
            return "\n[Response hint: They're in a good mood — match their energy.]"
        return ""


# Global singleton
reasoning_engine = ReasoningEngine()
