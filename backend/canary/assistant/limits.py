"""Per-crew rate limits for the assistant's paid calls (item 10): a token bucket for each crew member and kind.

Questions (`ask`), briefing builds (`briefing`) and suggestion builds (`suggestions`) each have a quota a minute. The bucket
refills smoothly (quota / 60 tokens a second), so a burst is allowed up to the quota and then one call every few seconds.
A refused call costs nothing: it writes no log row and calls no model. The clock is injected so tests never sleep.
Limits are per process and in memory: a restart gives everyone a full bucket again (acceptable for one on-board API).
"""
import math
import threading
import time
from typing import Callable, Dict, Optional, Tuple

PER_MINUTE: Dict[str, int] = {"ask": 10, "briefing": 3, "suggestions": 6}
WINDOW_S = 60.0


class Limiter:
    def __init__(self, rates: Optional[Dict[str, int]] = None, clock: Callable[[], float] = time.monotonic):
        self.rates = dict(PER_MINUTE if rates is None else rates)
        self.clock = clock
        self._state: Dict[Tuple[str, str], Tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, kind: str, crew_id: str) -> Optional[int]:
        """None when one more call is allowed (and counted); otherwise the whole seconds to wait before the next one."""
        cap = self.rates[kind]
        rate = cap / WINDOW_S
        now = self.clock()
        with self._lock:
            tokens, last = self._state.get((kind, crew_id), (float(cap), now))
            tokens = min(float(cap), tokens + max(0.0, now - last) * rate)
            if tokens >= 1:
                self._state[(kind, crew_id)] = (tokens - 1, now)
                return None
            self._state[(kind, crew_id)] = (tokens, now)
            return max(1, math.ceil((1 - tokens) / rate))


# The process-wide limiter. main.py looks it up at call time, so a test can replace it.
LIMITS = Limiter()
