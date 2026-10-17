"""Failed-login counter per (email, IP): lock 15 minutes after 5 consecutive failures (NFR-SEC-02, UC02).

The (email, IP) counter is the only thing that decides a lock (UC02 step 3); users.failed_logins/locked_until
only mirror the latest lock for display and audit. Valkey down → login fails closed with 503 (UC02 3b).
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Protocol

import valkey


class ThrottleUnavailable(Exception):
    pass


class LoginThrottle(Protocol):
    def locked_for(self, email: str, ip: str) -> int: ...
    def register_failure(self, email: str, ip: str) -> int: ...
    def reset(self, email: str, ip: str) -> None: ...
    def clear_email(self, email: str) -> None: ...


def _email_key(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:32]


class ValkeyLoginThrottle:
    """Keys: tastoria:login:fail:<email-hash>:<ip> (counter) and tastoria:login:lock:<email-hash>:<ip> (TTL)."""

    def __init__(self, client: valkey.Valkey, *, max_failures: int, lock_s: int) -> None:
        self.kv = client
        self.max_failures = max_failures
        self.lock_s = lock_s

    def _keys(self, email: str, ip: str) -> tuple[str, str]:
        h = _email_key(email)
        return f"tastoria:login:fail:{h}:{ip}", f"tastoria:login:lock:{h}:{ip}"

    def locked_for(self, email: str, ip: str) -> int:
        _, lock = self._keys(email, ip)
        try:
            ttl = int(self.kv.pttl(lock))
        except valkey.ValkeyError as exc:
            raise ThrottleUnavailable(str(exc)) from exc
        return max(0, -(-ttl // 1000)) if ttl > 0 else 0

    def register_failure(self, email: str, ip: str) -> int:
        """Counts one failure; returns lock seconds if this failure triggered a lock, else 0."""
        fail, lock = self._keys(email, ip)
        try:
            n = int(self.kv.incr(fail))
            if n == 1:
                self.kv.expire(fail, self.lock_s)
            if n >= self.max_failures:
                pipe = self.kv.pipeline()
                pipe.set(lock, "1", ex=self.lock_s)
                pipe.delete(fail)
                pipe.execute()
                return self.lock_s
            return 0
        except valkey.ValkeyError as exc:
            raise ThrottleUnavailable(str(exc)) from exc

    def reset(self, email: str, ip: str) -> None:
        fail, _ = self._keys(email, ip)
        try:
            self.kv.delete(fail)
        except valkey.ValkeyError as exc:
            raise ThrottleUnavailable(str(exc)) from exc

    def clear_email(self, email: str) -> None:
        h = _email_key(email)
        for pattern in (f"tastoria:login:fail:{h}:*", f"tastoria:login:lock:{h}:*"):
            keys = list(self.kv.scan_iter(match=pattern, count=500))
            if keys:
                self.kv.delete(*keys)


class MemoryLoginThrottle:
    """Single-process stand-in for local development without Valkey. Not for production (per-process state)."""

    def __init__(self, *, max_failures: int, lock_s: int) -> None:
        self.max_failures = max_failures
        self.lock_s = lock_s
        self._fail: dict[tuple[str, str], tuple[int, float]] = {}
        self._lock: dict[tuple[str, str], float] = {}
        self._mutex = threading.Lock()

    def locked_for(self, email: str, ip: str) -> int:
        k = (_email_key(email), ip)
        with self._mutex:
            until = self._lock.get(k, 0.0)
        left = until - time.monotonic()
        return int(-(-left // 1)) if left > 0 else 0

    def register_failure(self, email: str, ip: str) -> int:
        k = (_email_key(email), ip)
        now = time.monotonic()
        with self._mutex:
            n, exp = self._fail.get(k, (0, now + self.lock_s))
            if exp <= now:
                n, exp = 0, now + self.lock_s
            n += 1
            if n >= self.max_failures:
                self._lock[k] = now + self.lock_s
                self._fail.pop(k, None)
                return self.lock_s
            self._fail[k] = (n, exp)
            return 0

    def reset(self, email: str, ip: str) -> None:
        with self._mutex:
            self._fail.pop((_email_key(email), ip), None)

    def clear_email(self, email: str) -> None:
        h = _email_key(email)
        with self._mutex:
            for d in (self._fail, self._lock):
                for k in [k for k in d if k[0] == h]:
                    del d[k]
