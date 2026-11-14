"""In-memory sliding-window rate limiting dependency and utilities."""

from collections import defaultdict
import math
import threading
import time
from fastapi import HTTPException, Request, status


class SlidingWindowRateLimiter:
    """Thread-safe sliding-window in-memory rate limiter."""

    def __init__(self, requests_per_minute: int = 60, key_prefix: str = "default") -> None:
        self.requests_per_minute = requests_per_minute
        self.key_prefix = key_prefix
        self.window_seconds = 60.0
        self._history: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def get_client_ip(self, request: Request) -> str:
        """Extract client IP address respecting X-Forwarded-For headers if present."""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "127.0.0.1"

    def __call__(self, request: Request) -> None:
        """Evaluate incoming request against sliding window limit.

        Raises:
            HTTPException: 429 Too Many Requests if request count exceeds threshold.
        """
        ip = self.get_client_ip(request)
        key = f"{self.key_prefix}:{ip}"
        now = time.time()
        window_start = now - self.window_seconds

        with self._lock:
            # Purge expired timestamps outside the rolling 60-second window
            self._history[key] = [ts for ts in self._history[key] if ts > window_start]
            recent_requests = self._history[key]

            if len(recent_requests) >= self.requests_per_minute:
                # Oldest request in the window dictates when the next slot opens
                oldest_request = recent_requests[0]
                retry_after = max(1, math.ceil(oldest_request + self.window_seconds - now))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded. Maximum {self.requests_per_minute} requests per minute. Try again in {retry_after} seconds.",
                    headers={"Retry-After": str(retry_after)},
                )

            # Record current request timestamp
            recent_requests.append(now)

    def reset(self) -> None:
        """Clear rate limit history (primarily for automated testing)."""
        with self._lock:
            self._history.clear()


# Default rate limiters for general API routes and authentication
auth_rate_limiter = SlidingWindowRateLimiter(requests_per_minute=10, key_prefix="auth")
api_rate_limiter = SlidingWindowRateLimiter(requests_per_minute=60, key_prefix="api")
