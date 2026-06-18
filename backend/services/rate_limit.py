"""In-memory sliding-window rate limiter.

Single-process MVP implementation. For multi-worker / multi-instance
deployments, replace the in-memory store with Redis (same interface).
"""
import time
import threading
from collections import defaultdict, deque

_lock = threading.Lock()
_events: dict[str, deque] = defaultdict(deque)


def check_rate_limit(key: str, max_events: int, window_seconds: int) -> bool:
    """Record an event for `key` and return True if it is within the limit.

    Returns False when the limit has been exceeded (event is NOT recorded
    in that case, so a blocked caller does not extend their own window).
    """
    now = time.time()
    cutoff = now - window_seconds
    with _lock:
        q = _events[key]
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= max_events:
            return False
        q.append(now)
        return True
