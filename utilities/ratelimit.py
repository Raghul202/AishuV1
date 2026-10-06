"""
utilities/ratelimit.py — Per-user message rate limiting.
Prevents spam from hitting the AI API too frequently.
"""

import time
from collections import defaultdict, deque
from config.settings import RL_MESSAGES, RL_WINDOW


class RateLimiter:
    """Sliding window rate limiter per user ID."""

    def __init__(self, max_messages: int = RL_MESSAGES, window: float = RL_WINDOW):
        self.max_messages = max_messages
        self.window       = window
        self._history: dict[int, deque] = {}

    def is_limited(self, user_id: int) -> bool:
        """Return True if this user has sent too many messages recently."""
        now = time.monotonic()
        if len(self._history) > 300:
            # Clean up expired deques to keep memory bounded
            for uid in list(self._history.keys()):
                q = self._history.get(uid)
                if q and now - q[-1] > self.window:
                    self._history.pop(uid, None)
        dq = self._history.get(user_id)
        if dq is None:
            dq = deque()
            self._history[user_id] = dq

        # Drop expired timestamps
        while dq and now - dq[0] > self.window:
            dq.popleft()

        if len(dq) >= self.max_messages:
            return True

        dq.append(now)
        return False

    def cooldown(self, user_id: int) -> float:
        """Seconds until the user can send again."""
        now = time.monotonic()
        dq  = self._history.get(user_id)
        if not dq:
            return 0.0
        while dq and now - dq[0] > self.window:
            dq.popleft()
        if not dq:
            return 0.0
        oldest = dq[0]
        remaining = self.window - (now - oldest)
        return max(0.0, round(remaining, 1))

    def reset(self, user_id: int):
        """Manually reset rate limit for a user (admin use)."""
        self._history.pop(user_id, None)


# Global singleton
limiter = RateLimiter()
