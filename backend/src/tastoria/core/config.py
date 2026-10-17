"""Settings read from environment variables (prefix TASTORIA_). See backend/README.md for the full list.

Secrets (JWT keys, health-column keys, HMAC key) have no usable default in production: `Settings.check_production()`
refuses to start with the development placeholders when TASTORIA_ENV=production.
"""

from __future__ import annotations

import base64
import json
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_JWT_KEYS = {"dev-1": "dev-only-jwt-secret-change-me-0123456789abcdef"}
_DEV_ENC_KEYS = {"dev-1": base64.b64encode(b"\x00" * 32).decode()}
_DEV_HMAC = "dev-only-dsr-hmac-key"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TASTORIA_", extra="ignore")

    env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://tastoria:tastoria@127.0.0.1:5432/tastoria"
    db_pool_size: int = 5
    valkey_url: str = "redis://127.0.0.1:6379/0"
    # valkey: (email, IP) counters in Valkey (production). memory: one process only (local dev without Valkey).
    login_throttle_backend: Literal["valkey", "memory"] = "valkey"

    # identity (NFR-SEC-01, NFR-SEC-02, UC01, UC04)
    jwt_keys: dict[str, str] = Field(default_factory=lambda: dict(_DEV_JWT_KEYS))
    jwt_active_kid: str = "dev-1"
    jwt_issuer: str = "tastoria"
    jwt_audience: str = "tastoria-app"
    access_token_ttl_s: int = 900
    refresh_token_ttl_days: int = 30
    password_min_length: int = 10
    password_max_length: int = 128
    login_max_failures: int = 5
    login_lock_s: int = 900
    reset_token_ttl_s: int = 1800
    reset_resend_cooldown_s: int = 60
    reset_url_base: str = "https://tastoria.ctslab.net/dat-lai-mat-khau"

    # email (A09; dev: Mailpit on 127.0.0.1:1025)
    mailer: Literal["smtp", "log"] = "smtp"
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 1025
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = False
    mail_from: str = "Tastoria <no-reply@tastoria.ctslab.net>"

    # profile: AES-256-GCM keys for profiles.*_enc, base64 of 32 bytes, keyed by enc_key_id (ADR 0005)
    health_enc_keys: dict[str, str] = Field(default_factory=lambda: dict(_DEV_ENC_KEYS))
    health_enc_active_key_id: str = "dev-1"

    # privacy
    dsr_hmac_key: str = _DEV_HMAC
    storage_dir: str = "./var/storage"
    accel_redirect_prefix: str = "/_protected/"
    # sync: DSR jobs run right after the request commits (this slice). rq arrives with the scan slice.
    jobs_backend: Literal["sync"] = "sync"

    # API
    min_app_version: str = "0.0.0"
    log_level: str = "INFO"
    timezone: str = "Asia/Ho_Chi_Minh"

    @field_validator("jwt_keys", "health_enc_keys", mode="before")
    @classmethod
    def _json_dict(cls, v: object) -> object:
        if isinstance(v, str):
            return json.loads(v)
        return v

    def enc_key(self, key_id: str) -> bytes | None:
        raw = self.health_enc_keys.get(key_id)
        if raw is None:
            return None
        key = base64.b64decode(raw)
        if len(key) != 32:
            raise ValueError(f"health_enc_keys[{key_id}] must be 32 bytes (AES-256)")
        return key

    def check_production(self) -> None:
        if self.env != "production":
            return
        bad = []
        if any(v in _DEV_JWT_KEYS.values() for v in self.jwt_keys.values()):
            bad.append("TASTORIA_JWT_KEYS")
        if any(v in _DEV_ENC_KEYS.values() for v in self.health_enc_keys.values()):
            bad.append("TASTORIA_HEALTH_ENC_KEYS")
        if self.dsr_hmac_key == _DEV_HMAC:
            bad.append("TASTORIA_DSR_HMAC_KEY")
        if bad:
            raise RuntimeError("development secrets in production: " + ", ".join(bad))


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.check_production()
    return s
