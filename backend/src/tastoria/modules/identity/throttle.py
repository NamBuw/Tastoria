"""Failed-login counter per (email, IP) and across-IP per account (NFR-SEC-02, UC02).

Uses a single atomic Valkey Lua script for failure counting + expiry + lock promotion, and a bounded per-email
IP index set so `clear_email` never calls `SCAN`. Valkey down → login fails closed with 503 (UC02 3b).
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Protocol

import valkey

_REGISTER_FAILURE_LUA = """
local fail_ip = KEYS[1]
local lock_ip = KEYS[2]
local fail_email = KEYS[3]
local lock_email = KEYS[4]
local idx_key = KEYS[5]

local ip = ARGV[1]
local max_ip = tonumber(ARGV[2])
local max_email = tonumber(ARGV[3])
local lock_s = tonumber(ARGV[4])

redis.call('SADD', idx_key, ip)
redis.call('EXPIRE', idx_key, lock_s)

local n_ip = redis.call('INCR', fail_ip)
if n_ip == 1 then
    redis.call('EXPIRE', fail_ip, lock_s)
end

local n_email = redis.call('INCR', fail_email)
if n_email == 1 then
    redis.call('EXPIRE', fail_email, lock_s)
end

local locked = 0
if n_ip >= max_ip then
    redis.call('SET', lock_ip, '1', 'EX', lock_s)
    redis.call('DEL', fail_ip)
    locked = lock_s
end

if n_email >= max_email then
    redis.call('SET', lock_email, '1', 'EX', lock_s)
    redis.call('DEL', fail_email)
    locked = lock_s
end

return locked
"""


class ThrottleUnavailable(Exception):
    pass


class LoginThrottle(Protocol):
    def locked_for(self, email: str, ip: str) -> int: ...
    def register_failure(self, email: str, ip: str) -> int: ...
    def reset(self, email: str, ip: str) -> None: ...
    def clear_email(self, email: str) -> None: ...


def _email_key(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:32]


def _ttl_to_s(ttl_ms: int) -> int:
    return max(0, -(-ttl_ms // 1000)) if ttl_ms > 0 else 0


class ValkeyLoginThrottle:
    """Atomic per-(email, IP) and across-IP per-email login lockout backed by Valkey."""

    def __init__(
        self,
        client: valkey.Valkey,
        *,
        max_failures: int,
        lock_s: int,
        email_max_failures: int | None = None,
    ) -> None:
        self.kv = client
        self.max_failures = max_failures
        self.email_max_failures = email_max_failures if email_max_failures is not None else max_failures * 3
        self.lock_s = lock_s

    def _keys(self, email: str, ip: str) -> tuple[str, str, str, str, str]:
        h = _email_key(email)
        return (
            f"tastoria:login:fail:{h}:{ip}",
            f"tastoria:login:lock:{h}:{ip}",
            f"tastoria:login:email_fail:{h}",
            f"tastoria:login:email_lock:{h}",
            f"tastoria:login:email_keys:{h}",
        )

    def locked_for(self, email: str, ip: str) -> int:
        _, lock_ip, _, lock_email, _ = self._keys(email, ip)
        try:
            pipe = self.kv.pipeline()
            pipe.pttl(lock_ip)
            pipe.pttl(lock_email)
            t_ip, t_email = pipe.execute()
        except valkey.ValkeyError as exc:
            raise ThrottleUnavailable(str(exc)) from exc
        return max(_ttl_to_s(int(t_ip)), _ttl_to_s(int(t_email)))

    def register_failure(self, email: str, ip: str) -> int:
        """Counts one failure atomically; returns lock seconds if this failure triggered a lock, else 0."""
        fail_ip, lock_ip, fail_email, lock_email, idx_key = self._keys(email, ip)
        try:
            res = self.kv.eval(
                _REGISTER_FAILURE_LUA,
                5,
                fail_ip,
                lock_ip,
                fail_email,
                lock_email,
                idx_key,
                ip,
                str(self.max_failures),
                str(self.email_max_failures),
                str(self.lock_s),
            )
        except valkey.ValkeyError as exc:
            raise ThrottleUnavailable(str(exc)) from exc
        return int(res or 0)

    def reset(self, email: str, ip: str) -> None:
        fail_ip, _, fail_email, _, _ = self._keys(email, ip)
        try:
            self.kv.delete(fail_ip, fail_email)
        except valkey.ValkeyError as exc:
            raise ThrottleUnavailable(str(exc)) from exc

    def clear_email(self, email: str) -> None:
        h = _email_key(email)
        idx_key = f"tastoria:login:email_keys:{h}"
        keys = [f"tastoria:login:email_fail:{h}", f"tastoria:login:email_lock:{h}", idx_key]
        try:
            members = self.kv.smembers(idx_key)
            for raw_ip in members:
                ip = raw_ip.decode("utf-8") if isinstance(raw_ip, bytes) else str(raw_ip)
                keys.append(f"tastoria:login:fail:{h}:{ip}")
                keys.append(f"tastoria:login:lock:{h}:{ip}")
            self.kv.delete(*keys)
        except valkey.ValkeyError as exc:
            raise ThrottleUnavailable(str(exc)) from exc


class MemoryLoginThrottle:
    """Single-process stand-in for local development without Valkey. Not for production (per-process state)."""

    def __init__(
        self,
        *,
        max_failures: int,
        lock_s: int,
        email_max_failures: int | None = None,
    ) -> None:
        self.max_failures = max_failures
        self.email_max_failures = email_max_failures if email_max_failures is not None else max_failures * 3
        self.lock_s = lock_s
        self._fail: dict[tuple[str, str], tuple[int, float]] = {}
        self._lock: dict[tuple[str, str], float] = {}
        self._email_fail: dict[str, tuple[int, float]] = {}
        self._email_lock: dict[str, float] = {}
        self._mutex = threading.Lock()

    def locked_for(self, email: str, ip: str) -> int:
        h = _email_key(email)
        k = (h, ip)
        now = time.monotonic()
        with self._mutex:
            until = max(self._lock.get(k, 0.0), self._email_lock.get(h, 0.0))
        left = until - now
        return int(-(-left // 1)) if left > 0 else 0

    def register_failure(self, email: str, ip: str) -> int:
        h = _email_key(email)
        k = (h, ip)
        now = time.monotonic()
        locked = 0
        with self._mutex:
            n_ip, exp_ip = self._fail.get(k, (0, now + self.lock_s))
            if exp_ip <= now:
                n_ip, exp_ip = 0, now + self.lock_s
            n_ip += 1
            if n_ip >= self.max_failures:
                self._lock[k] = now + self.lock_s
                self._fail.pop(k, None)
                locked = self.lock_s
            else:
                self._fail[k] = (n_ip, exp_ip)

            n_em, exp_em = self._email_fail.get(h, (0, now + self.lock_s))
            if exp_em <= now:
                n_em, exp_em = 0, now + self.lock_s
            n_em += 1
            if n_em >= self.email_max_failures:
                self._email_lock[h] = now + self.lock_s
                self._email_fail.pop(h, None)
                locked = self.lock_s
            else:
                self._email_fail[h] = (n_em, exp_em)
        return locked

    def reset(self, email: str, ip: str) -> None:
        h = _email_key(email)
        with self._mutex:
            self._fail.pop((h, ip), None)
            self._email_fail.pop(h, None)

    def clear_email(self, email: str) -> None:
        h = _email_key(email)
        with self._mutex:
            for d in (self._fail, self._lock):
                for k in [k for k in d if k[0] == h]:
                    del d[k]
            self._email_fail.pop(h, None)
            self._email_lock.pop(h, None)
