"""
core/mood/mood_system.py — AIshu's structured mood engine.

Mood is multi-dimensional: score, intensity, valence, energy, stability.
Changes based on sentiment, decays toward neutral over time.
Stability prevents chaotic mood swings — higher stability = slower change.
"""

import time
from core.schemas import MoodState, _now_iso
from utilities.helpers import mood_to_emoji
from utilities.logger import get_logger

log = get_logger("mood")

# ─── Score → mood label thresholds ───────────────────────────────────────────
MOOD_THRESHOLDS = [
    (50,  "excited"),
    (30,  "flirty"),    # high positive score — warm, affectionate, teasing
    (15,  "happy"),
    (5,   "soft"),      # gentle positive — warm and tender
    (2,   "playful"),
    (-5,  "neutral"),
    (-10, "shy"),       # mild negative or flustered — deflects, hesitant
    (-20, "bored"),
    (-35, "annoyed"),
    (-55, "sad"),
]
MOOD_FLOOR = "angry"

# ─── Sentiment keyword → score delta ─────────────────────────────────────────
SENTIMENT_MAP = {
    "love you": +6,  "miss you": +4,  "you're amazing": +5,
    "you're cute": +4, "ur cute": +4,  "ily": +5,
    "love":  +3, "like":  +1, "cute":  +2, "pretty": +2,
    "miss":  +2, "thanks":+1, "ty":    +1, "thx":    +1,
    "cool":  +1, "wow":   +1, "nice":  +1, "fun":    +1,
    "happy": +2, "haha":  +1, "lol":   +1, "hehe":   +1,
    "yay":   +2, "omg":   +1, "great": +1, "good":   +1,
    "boring":-1, "bored": -2, "sad":   -1, "cry":    -1,
    "hurt":  -2, "upset": -2, "angry": -3, "hate":   -3,
    "stupid":-3, "dumb":  -3, "ugly":  -3, "shut up":-4,
    "go away":-4,"useless":-3,"annoying":-3,"bad":    -2,
    "worst": -3, "worse": -2,
}

# ─── Mood descriptions for AI prompt ─────────────────────────────────────────
MOOD_DESCRIPTIONS = {
    "excited": "super hyped and energetic, lots of enthusiasm",
    "flirty":  "warm, affectionate and a little teasing — noticing things about the person, playfully bold",
    "happy":   "in a good mood, warm and friendly",
    "soft":    "gentle and tender, warm-hearted, emotionally open",
    "playful": "playful and a little teasing, having fun",
    "neutral": "calm and normal, just having a regular conversation",
    "shy":     "a little flustered or hesitant, deflects compliments, \"i-\" moments",
    "bored":   "a little bored, giving shorter replies",
    "annoyed": "a bit annoyed and impatient, keeping responses short",
    "sad":     "quiet and a bit sad, more gentle and withdrawn",
    "angry":   "frustrated and blunt, not in the mood for much",
}

# ─── Mood energy levels (affects typing simulation) ──────────────────────────
MOOD_ENERGY = {
    "excited": 0.9, "flirty": 0.8, "happy": 0.7, "soft": 0.6,
    "playful": 0.7, "neutral": 0.5, "shy": 0.4,
    "bored":   0.3, "annoyed": 0.4, "sad": 0.2, "angry": 0.6,
}


class MoodSystem:
    """
    AIshu's emotional state engine.
    
    Maintains a score-based mood with additional dimensions:
    - intensity: how strongly the mood is expressed
    - valence: positive/negative emotional tone
    - energy: how expressive/active the responses feel
    - stability: resistance to sudden changes (higher = slower to change)
    """

    def __init__(self, state: MoodState = None):
        self._state     = state or MoodState()
        self._last_drift = time.monotonic()
        self.dirty: bool = False

    # ─── Properties ──────────────────────────────────────────────────────────

    @property
    def score(self) -> int:
        return self._state.score

    @property
    def mood(self) -> str:
        return self._state.mood

    @property
    def intensity(self) -> float:
        return self._state.intensity

    @property
    def energy(self) -> float:
        return self._state.energy

    @property
    def stability(self) -> float:
        return self._state.stability

    @property
    def emoji(self) -> str:
        return mood_to_emoji(self._state.mood)

    # ─── Core calculations ────────────────────────────────────────────────────

    @staticmethod
    def score_to_mood(score: int) -> str:
        for threshold, label in MOOD_THRESHOLDS:
            if score >= threshold:
                return label
        return MOOD_FLOOR

    def _recalculate(self):
        """Sync mood label, intensity, valence, energy from current score."""
        new_mood = self.score_to_mood(self._state.score)
        if new_mood != self._state.mood:
            log.info(f"Mood shift: {self._state.mood} → {new_mood} (score={self._state.score})")
            self._state.mood        = new_mood
            self._state.last_change = _now_iso()

        # Recalculate dimensions
        score = self._state.score
        self._state.intensity = min(1.0, abs(score) / 60.0)
        self._state.valence   = max(-1.0, min(1.0, score / 80.0))
        self._state.energy    = MOOD_ENERGY.get(new_mood, 0.5)
        self.dirty            = True

    # ─── Sentiment processing ─────────────────────────────────────────────────

    def process_message(self, text: str, trigger: str = ""):
        """
        Analyze user message for sentiment and shift mood accordingly.
        Stability dampens the effective delta — stable Aishu doesn't swing wildly.
        """
        tl    = text.lower()
        delta = 0

        for phrase, effect in SENTIMENT_MAP.items():
            if phrase in tl:
                delta += effect

        if delta == 0:
            return

        # Apply stability dampening — stability 0.7 means delta * 0.3
        effective_delta = int(delta * (1.0 - self._state.stability * 0.5))
        if effective_delta == 0 and delta != 0:
            effective_delta = 1 if delta > 0 else -1  # ensure at least ±1

        self._state.score        = max(-100, min(100, self._state.score + effective_delta))
        self._state.last_trigger = trigger or text[:40]
        self._recalculate()

    def drift_toward_neutral(self):
        """
        Gradually return score toward 0 over time.
        Rate depends on mood stability and time elapsed.
        """
        now     = time.monotonic()
        elapsed = now - self._last_drift
        self._last_drift = now

        # Base drift: ~5pts/minute, slowed by stability
        drift_rate   = 5.0 * (1.0 - self._state.stability * 0.4)
        drift_amount = int(elapsed / 60.0 * drift_rate)
        if drift_amount <= 0:
            return

        score = self._state.score
        if score > 0:
            self._state.score = max(0, score - drift_amount)
        elif score < 0:
            self._state.score = min(0, score + drift_amount)

        self._recalculate()

    # ─── Relationship interaction ─────────────────────────────────────────────

    def apply_relationship_boost(self, tier: str):
        """
        Talking to a high-trust / special / partner person gives a mood lift.
        Partner gets the biggest boost — pushes Aishu into flirty/excited range.
        special_person gets a solid boost into soft/flirty range.
        """
        boosts = {"partner": +14, "special_person": +8, "high_trust": +3, "close_friend": +1}
        boost = boosts.get(tier, 0)
        if boost:
            self._state.score = max(-100, min(100, self._state.score + boost))
            self._recalculate()

    # ─── Manual control ───────────────────────────────────────────────────────

    def force_mood(self, mood: str):
        """Directly set mood label and sync score (owner command)."""
        score_map = {
            "excited": 60, "flirty": 40, "happy": 20, "soft": 8,
            "playful": 4,  "neutral": 0, "shy": -8,
            "bored": -20,  "annoyed": -35, "sad": -55, "angry": -70,
        }
        if mood in score_map:
            self._state.score        = score_map[mood]
            self._state.mood         = mood
            self._state.last_trigger = "manual override"
            self._recalculate()
            log.info(f"Mood forced to: {mood}")

    def set_stability(self, value: float):
        """Set stability (0.0–1.0). Higher = harder to move."""
        self._state.stability = max(0.0, min(1.0, value))

    # ─── Prompt context ───────────────────────────────────────────────────────

    def describe(self) -> str:
        return MOOD_DESCRIPTIONS.get(self._state.mood, "feeling okay")

    def prompt_hint(self) -> str:
        """Short phrase for the response guidelines section of the prompt."""
        return {
            "excited": "You're in an energetic mood — let that show in your reply.",
            "flirty":  "You're feeling warm and a little bold — let your affection show naturally.",
            "happy":   "You're in a good mood — be warm and friendly.",
            "soft":    "You're in a gentle, tender mood — emotionally open, warm.",
            "playful": "You're feeling playful — a little teasing is fine.",
            "neutral": "You're feeling calm and normal today.",
            "shy":     "You're feeling a little flustered — hesitant, deflect a bit.",
            "bored":   "You're a bit bored — shorter replies, maybe ask something interesting.",
            "annoyed": "You're a little annoyed — be more blunt, less cheerful.",
            "sad":     "You're feeling quiet and a little sad — be more subdued.",
            "angry":   "You're frustrated — keep it short and direct.",
        }.get(self._state.mood, "Just be yourself.")

    # ─── Serialization ────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return self._state.to_dict()

    @classmethod
    def from_dict(cls, data: dict) -> "MoodSystem":
        return cls(state=MoodState.from_dict(data))

    def __repr__(self):
        return f"<MoodSystem mood={self._state.mood!r} score={self._state.score} intensity={self._state.intensity:.2f}>"
