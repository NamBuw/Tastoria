"""Sliding-window rate limiting (Valkey Lua + single-process memory fallback) and trusted-proxy IP extraction."""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import math
import threading
import time
import uuid
from collections import defaultdict, deque
from functools import lru_cache
from typing import Protocol

import valkey
from fastapi import Request

from tastoria.core.config import Settings
from tastoria.core.errors import ApiError, ProblemCode

log = logging.getLogger("tastoria.ratelimit")

IPAddr = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNet = ipaddress.IPv4Network | ipaddress.IPv6Network

_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, '-inf', now_ms - window_ms)
local count = redis.call('ZCARD', key)
if count >= limit then
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_ms = window_ms
    if oldest[2] then
        retry_ms = math.max(1, window_ms - (now_ms - tonumber(oldest[2])))
    end
    return {0, retry_ms}
end
redis.call('ZADD', key, now_ms, member)
redis.call('PEXPIRE', key, window_ms)
return {1, 0}
"""


@lru_cache(maxsize=32)
def _trusted_networks(cidrs: tuple[str, ...]) -> tuple[IPNet, ...]:
    nets: list[IPNet] = []
    for raw in cidrs:
        item = raw.strip()
        if not item:
            continue
        try:
            nets.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            log.warning("ignoring invalid trusted_proxy CIDR", extra={"cidr": item})
    return tuple(nets)


def _parse_ip(raw: str | None) -> IPAddr | None:
    if not raw:
        return None
    cand = raw.strip()
    if not cand:
        return None
    try:
        return ipaddress.ip_address(cand)
    except ValueError:
        return None


def _is_trusted(ip: IPAddr, nets: tuple[IPNet, ...]) -> bool:
    return any(ip in net for net in nets)


def client_ip(request: Request, settings: Settings) -> str:
    """Extract canonical client IP, trusting forwarded headers ONLY when the immediate peer is a trusted proxy."""
    peer_raw = (request.client.host if request.client else "").strip()
    peer_ip = _parse_ip(peer_raw)
    if peer_ip is None:
        return peer_raw or "unknown"

    nets = _trusted_networks(tuple(settings.trusted_proxies))
    if not _is_trusted(peer_ip, nets):
        return peer_ip.compressed

    for header in ("cf-connecting-ip", "x-real-ip"):
        cand_ip = _parse_ip(request.headers.get(header))
        if cand_ip is not None:
            return cand_ip.compressed

    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        parsed = [_parse_ip(part) for part in xff.split(",")]
        valid = [ip for ip in parsed if ip is not None]
        if valid:
            for ip in reversed(valid):
                if not _is_trusted(ip, nets):
                    return ip.compressed
            return valid[0].compressed

    return peer_ip.compressed


def email_subject(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:32]


class RateLimiter(Protocol):
    def hit(self, bucket: str, subject: str, *, limit: int, window_s: int) -> None: ...


class ValkeyRateLimiter:
    """Atomic sliding-window rate limiter backed by Valkey ZSET + Lua; fails closed (503) on Valkey errors."""

    def __init__(self, client: valkey.Valkey, *, enabled: bool = True) -> None:
        self.kv = client
        self.enabled = enabled

    def hit(self, bucket: str, subject: str, *, limit: int, window_s: int) -> None:
        if not self.enabled:
            return
        key = f"tastoria:rl:{bucket}:{subject}"
        now_ms = int(time.time() * 1000)
        window_ms = max(1, int(window_s * 1000))
        member = f"{now_ms}:{uuid.uuid4().hex}"
        try:
            res = self.kv.eval(_SLIDING_WINDOW_LUA, 1, key, str(now_ms), str(window_ms), str(limit), member)
        except valkey.ValkeyError as exc:
            log.error("rate limiter unavailable; failing closed", extra={"bucket": bucket})
            raise ApiError(503, ProblemCode.service_unavailable, headers={"Retry-After": "5"}) from exc

        if not isinstance(res, list | tuple) or len(res) < 2:
            log.error("unexpected valkey rate limiter reply", extra={"bucket": bucket})
            raise ApiError(503, ProblemCode.service_unavailable, headers={"Retry-After": "5"})

        allowed = int(res[0])
        if allowed == 0:
            retry_ms = int(res[1])
            retry_after = max(1, math.ceil(retry_ms / 1000))
            raise ApiError(429, ProblemCode.rate_limited, headers={"Retry-After": str(retry_after)})


class MemoryRateLimiter:
    """Thread-safe in-memory sliding-window rate limiter for local development and tests."""

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self._buckets: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, bucket: str, subject: str, *, limit: int, window_s: int) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        cutoff = now - window_s
        k = (bucket, subject)
        with self._lock:
            dq = self._buckets[k]
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) >= limit:
                retry_after = max(1, math.ceil((dq[0] + window_s) - now))
                raise ApiError(429, ProblemCode.rate_limited, headers={"Retry-After": str(retry_after)})
            dq.append(now)


def enforce_rate_limit(request: Request, *, bucket: str, subject: str, limit: int, window_s: int) -> None:
    limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        return
    limiter.hit(bucket, subject, limit=limit, window_s=window_s)
