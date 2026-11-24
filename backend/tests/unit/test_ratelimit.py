"""Unit tests for M4-2 P1-3: ValkeyLoginThrottle (atomic Lua, across-IP, SCAN-free clear_email), MemoryLoginThrottle, and check_password_throttled."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import valkey

from tastoria.core.errors import ApiError, ProblemCode
from tastoria.modules.identity import passwords
from tastoria.modules.identity import service as identity_service
from tastoria.modules.identity.throttle import MemoryLoginThrottle, ThrottleUnavailable, ValkeyLoginThrottle, _email_key


class _FakeValkey:
    """In-memory Valkey mock supporting eval (exact M4-2 Lua semantics), pipeline(pttl), delete, smembers, and forbidding scan_iter."""

    def __init__(self, *, err: Exception | None = None) -> None:
        self.err = err
        self.kv: dict[str, str] = {}
        self.ttls_ms: dict[str, int] = {}
        self.sets: dict[str, set[str]] = {}
        self.eval_calls: list[tuple[int, tuple[object, ...]]] = []

    def _raise_if_err(self) -> None:
        if self.err is not None:
            raise self.err

    def scan_iter(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("scan_iter MUST NEVER be called in ValkeyLoginThrottle")

    def eval(self, script: str, numkeys: int, *args: object) -> int:
        self._raise_if_err()
        assert numkeys == 5
        assert "SADD" in script and "INCR" in script and "EXPIRE" in script
        self.eval_calls.append((numkeys, args))
        fail_ip, lock_ip, fail_email, lock_email, idx_key = (str(args[i]) for i in range(5))
        ip = str(args[5])
        max_ip = int(str(args[6]))
        max_email = int(str(args[7]))
        lock_s = int(str(args[8]))

        self.sets.setdefault(idx_key, set()).add(ip)
        self.ttls_ms[idx_key] = lock_s * 1000

        n_ip = int(self.kv.get(fail_ip, "0")) + 1
        self.kv[fail_ip] = str(n_ip)
        if n_ip == 1:
            self.ttls_ms[fail_ip] = lock_s * 1000

        n_em = int(self.kv.get(fail_email, "0")) + 1
        self.kv[fail_email] = str(n_em)
        if n_em == 1:
            self.ttls_ms[fail_email] = lock_s * 1000

        locked = 0
        if n_ip >= max_ip:
            self.kv[lock_ip] = "1"
            self.ttls_ms[lock_ip] = lock_s * 1000
            self.kv.pop(fail_ip, None)
            self.ttls_ms.pop(fail_ip, None)
            locked = lock_s
        if n_em >= max_email:
            self.kv[lock_email] = "1"
            self.ttls_ms[lock_email] = lock_s * 1000
            self.kv.pop(fail_email, None)
            self.ttls_ms.pop(fail_email, None)
            locked = lock_s
        return locked

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self)

    def smembers(self, key: str) -> set[bytes]:
        self._raise_if_err()
        return {m.encode("utf-8") for m in self.sets.get(key, set())}

    def delete(self, *keys: str) -> int:
        self._raise_if_err()
        removed = 0
        for k in keys:
            if k in self.kv:
                del self.kv[k]
                removed += 1
            self.ttls_ms.pop(k, None)
            if k in self.sets:
                del self.sets[k]
                removed += 1
        return removed


class _FakePipeline:
    def __init__(self, parent: _FakeValkey) -> None:
        self.parent = parent
        self.ops: list[str] = []

    def pttl(self, key: str) -> _FakePipeline:
        self.ops.append(key)
        return self

    def execute(self) -> list[int]:
        self.parent._raise_if_err()
        return [self.parent.ttls_ms.get(k, -2) for k in self.ops]


def test_valkey_login_throttle_atomic_lua_across_ip_and_scan_free_clear() -> None:
    kv = _FakeValkey()
    t = ValkeyLoginThrottle(kv, max_failures=5, lock_s=900)  # type: ignore[arg-type]

    # 1. Per-(email, ip) triggers lock on 5th failure via single atomic Lua eval
    for _ in range(4):
        assert t.register_failure("User@Example.vn", "1.1.1.1") == 0
        assert t.locked_for("user@example.vn", "1.1.1.1") == 0
    assert t.register_failure("user@example.vn", "1.1.1.1") == 900
    assert len(kv.eval_calls) == 5
    assert t.locked_for("user@example.vn", "1.1.1.1") == 900
    # Another IP is not locked yet (across-IP count is 5 < 15)
    assert t.locked_for("user@example.vn", "2.2.2.2") == 0

    # 2. Across-IP lockout triggers at 15 total failures across distinct IPs
    for i in range(9):
        assert t.register_failure("user@example.vn", f"10.0.0.{i}") == 0
    assert t.register_failure("user@example.vn", "10.0.0.99") == 900
    # Now even a brand-new unseen IP is locked for this email!
    assert t.locked_for("user@example.vn", "9.9.9.9") == 900

    # 3. clear_email removes all tracked keys using smembers + delete (never calls scan_iter)
    h = _email_key("user@example.vn")
    assert len(kv.sets[f"tastoria:login:email_keys:{h}"]) >= 10
    t.clear_email("user@example.vn")
    assert t.locked_for("user@example.vn", "1.1.1.1") == 0
    assert t.locked_for("user@example.vn", "9.9.9.9") == 0
    assert kv.kv == {} and kv.sets == {}


def test_valkey_login_throttle_reset_and_fail_closed() -> None:
    kv = _FakeValkey()
    t = ValkeyLoginThrottle(kv, max_failures=5, lock_s=300)  # type: ignore[arg-type]
    for _ in range(3):
        t.register_failure("a@b.vn", "1.2.3.4")
    t.reset("a@b.vn", "1.2.3.4")
    # Reset cleared both fail_ip and fail_email, so 4 more failures don't lock
    for _ in range(4):
        assert t.register_failure("a@b.vn", "1.2.3.4") == 0

    down = ValkeyLoginThrottle(_FakeValkey(err=valkey.ConnectionError("down")), max_failures=5, lock_s=300)  # type: ignore[arg-type]
    with pytest.raises(ThrottleUnavailable):
        down.locked_for("a@b.vn", "1.2.3.4")
    with pytest.raises(ThrottleUnavailable):
        down.register_failure("a@b.vn", "1.2.3.4")
    with pytest.raises(ThrottleUnavailable):
        down.reset("a@b.vn", "1.2.3.4")
    with pytest.raises(ThrottleUnavailable):
        down.clear_email("a@b.vn")


def test_memory_login_throttle_per_ip_and_across_ip() -> None:
    t = MemoryLoginThrottle(max_failures=2, lock_s=60)  # email_max_failures = 6
    assert t.register_failure("x@y.vn", "1.1.1.1") == 0
    assert t.register_failure("x@y.vn", "1.1.1.1") == 60
    assert t.locked_for("x@y.vn", "1.1.1.1") > 0
    assert t.locked_for("x@y.vn", "2.2.2.2") == 0

    # 4 more failures across distinct IPs hit email_max_failures=6
    for idx in range(3):
        assert t.register_failure("x@y.vn", f"3.3.3.{idx}") == 0
    assert t.register_failure("x@y.vn", "4.4.4.4") == 60
    assert t.locked_for("x@y.vn", "5.5.5.5") > 0

    t.clear_email("x@y.vn")
    assert t.locked_for("x@y.vn", "1.1.1.1") == 0
    assert t.locked_for("x@y.vn", "5.5.5.5") == 0


def test_check_password_throttled_behavior() -> None:
    uid = uuid.uuid4()
    pw_hash = passwords.hash_password("dung-mat-khau-10")
    user = SimpleNamespace(id=uid, password_hash=pw_hash, locked_until=None)

    class _FakeSession:
        def __init__(self, u: object) -> None:
            self.u = u

        def get(self, model: object, key: object) -> object:
            return self.u

    sess = _FakeSession(user)
    throttle = MemoryLoginThrottle(max_failures=3, lock_s=120)

    # Wrong password returns False until threshold, then raises 429 login_locked
    assert identity_service.check_password_throttled(sess, throttle, uid, "wrong", "1.2.3.4") is False  # type: ignore[arg-type]
    assert identity_service.check_password_throttled(sess, throttle, uid, "wrong", "1.2.3.4") is False  # type: ignore[arg-type]
    with pytest.raises(ApiError) as exc_lock:
        identity_service.check_password_throttled(sess, throttle, uid, "wrong", "1.2.3.4")  # type: ignore[arg-type]
    assert (exc_lock.value.status, exc_lock.value.code) == (429, ProblemCode.login_locked)
    assert int(exc_lock.value.headers["Retry-After"]) == 120

    # Even with right password, locked throttle rejects with 429
    with pytest.raises(ApiError) as exc_still_locked:
        identity_service.check_password_throttled(sess, throttle, uid, "dung-mat-khau-10", "1.2.3.4")  # type: ignore[arg-type]
    assert exc_still_locked.value.code == ProblemCode.login_locked

    # Clear throttle; DB user.locked_until in future also rejects with 429 BEFORE verify
    throttle.clear_email(f"reauth:{uid}")
    user.locked_until = datetime.now(UTC) + timedelta(seconds=60)
    with pytest.raises(ApiError) as exc_db_lock:
        identity_service.check_password_throttled(sess, throttle, uid, "dung-mat-khau-10", "1.2.3.4")  # type: ignore[arg-type]
    assert exc_db_lock.value.code == ProblemCode.login_locked

    # Valid password succeeds and resets counter
    user.locked_until = None
    assert identity_service.check_password_throttled(sess, throttle, uid, "wrong", "1.2.3.4") is False  # type: ignore[arg-type]
    assert identity_service.check_password_throttled(sess, throttle, uid, "dung-mat-khau-10", "1.2.3.4") is True  # type: ignore[arg-type]

    # ThrottleUnavailable fails closed with 503
    down = ValkeyLoginThrottle(_FakeValkey(err=valkey.ConnectionError("down")), max_failures=3, lock_s=120)  # type: ignore[arg-type]
    with pytest.raises(ApiError) as exc_503:
        identity_service.check_password_throttled(sess, down, uid, "dung-mat-khau-10", "1.2.3.4")  # type: ignore[arg-type]
    assert (exc_503.value.status, exc_503.value.code) == (503, ProblemCode.service_unavailable)
