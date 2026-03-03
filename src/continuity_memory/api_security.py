from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field


@dataclass
class ApiSecurityConfig:
    enabled: bool = False
    tokens: dict[str, str] = field(default_factory=dict)
    admin_tokens: set[str] = field(default_factory=set)
    tenant_header_name: str = "X-Tenant-Id"
    conversation_id_format: str = "{tenant}:{conversation}"
    require_auth_for_loopback: bool = False
    rate_limit_per_minute: int = 120
    max_body_bytes: int = 1024 * 1024


@dataclass
class AuthContext:
    token: str
    tenant: str
    is_admin: bool


@dataclass
class RateLimiter:
    limit: int
    window_seconds: float = 60.0
    _events: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def allow(self, key: str, now: float | None = None) -> bool:
        ts_now = now if now is not None else time.time()
        with self._lock:
            bucket = self._events[key]
            while bucket and ts_now - bucket[0] > self.window_seconds:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(ts_now)
            return True
