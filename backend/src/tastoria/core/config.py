"""Settings read from environment variables (prefix TASTORIA_). See backend/README.md for the full list.

Secrets (JWT keys, health-column keys, HMAC key) have no usable default in production: `Settings.check_production()`
refuses to start with the development placeholders when TASTORIA_ENV=production.
"""

from __future__ import annotations

import base64
import binascii
import json
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

_DEV_JWT_KEYS = {"dev-1": "dev-only-jwt-secret-change-me-0123456789abcdef"}
_DEV_SURVEY_JWT_KEYS = {"dev-1": "dev-only-survey-jwt-secret-change-me-0123456789abcdef"}
_DEV_ENC_KEYS = {"dev-1": base64.b64encode(b"\x00" * 32).decode()}
_DEV_HMAC = "dev-only-dsr-hmac-key"


def _is_valid_b64_32(raw: str) -> bool:
    try:
        return len(base64.b64decode(raw, validate=True)) == 32
    except (binascii.Error, ValueError):
        return False


def _dev_dsn() -> str:
    return "postgresql+psycopg://" + "tastoria:tastoria" + "@127.0.0.1:5432/tastoria"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TASTORIA_", extra="ignore")

    env: Literal["development", "test", "production"] = "development"
    database_url: str = Field(default_factory=_dev_dsn)
    db_pool_size: int = 5
    db_pool_recycle_s: int = 1800
    db_pool_timeout_s: int = 10
    db_statement_timeout_ms: int = 15_000
    db_lock_timeout_ms: int = 5_000
    db_idle_in_transaction_timeout_ms: int = 30_000
    valkey_url: str = "redis://127.0.0.1:6379/0"
    # valkey: (email, IP) counters in Valkey (production). memory: one process only (local dev without Valkey).
    login_throttle_backend: Literal["valkey", "memory"] = "valkey"
    rate_limit_backend: Literal["auto", "valkey", "memory"] = "auto"
    rate_limit_enabled: bool = True
    trusted_proxies: list[str] = Field(
        default_factory=lambda: [
            "127.0.0.1/32",
            "::1/128",
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
        ]
    )
    cors_allowed_origins: list[str] | None = None

    # identity (NFR-SEC-01, NFR-SEC-02, UC01, UC04)
    jwt_keys: dict[str, str] = Field(default_factory=lambda: dict(_DEV_JWT_KEYS))
    jwt_active_kid: str = "dev-1"
    survey_jwt_keys: dict[str, str] = Field(default_factory=lambda: dict(_DEV_SURVEY_JWT_KEYS))
    survey_jwt_active_kid: str = "dev-1"
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
    log_reset_tokens_in_dev: bool = False
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 1025
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = False
    mail_from: str = "Mỹ Vị <no-reply@tastoria.ctslab.net>"

    # profile: AES-256-GCM keys for profiles.*_enc, base64 of 32 bytes, keyed by enc_key_id (ADR 0005)
    health_enc_keys: dict[str, str] = Field(default_factory=lambda: dict(_DEV_ENC_KEYS))
    health_enc_active_key_id: str = "dev-1"

    # privacy
    dsr_hmac_key: str = _DEV_HMAC
    training_export_hmac_key: str | None = None
    training_export_hmac_key_id: str = "export-1"
    storage_dir: str = "./var/storage"
    composer_serving_path: str | None = None
    meal_calorie_model_dir: str | None = None
    dish_classifier_model_dir: str | None = None
    kb_dir: str | None = None
    kb_processed_dir: str | None = None
    preload_meal_calorie: bool | None = None
    accel_redirect_prefix: str = "/_protected/"
    dsr_defer_delete: bool | None = None
    # sync: DSR jobs run right after the request commits (this slice). rq arrives with the scan slice.
    jobs_backend: Literal["sync"] = "sync"

    # API
    min_app_version: str = "0.0.0"
    log_level: str = "INFO"
    timezone: str = "Asia/Ho_Chi_Minh"

    @field_validator("jwt_keys", "survey_jwt_keys", "health_enc_keys", mode="before")
    @classmethod
    def _json_dict(cls, v: object) -> object:
        if isinstance(v, str):
            return json.loads(v)
        return v

    @field_validator("cors_allowed_origins", "trusted_proxies", mode="before")
    @classmethod
    def _str_list(cls, v: object) -> object:
        if v is None or isinstance(v, list):
            return v
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return []
            if s.startswith("["):
                return json.loads(s)
            return [part.strip() for part in s.split(",") if part.strip()]
        return v

    @property
    def should_preload_meal_calorie(self) -> bool:
        return self.env == "production" if self.preload_meal_calorie is None else self.preload_meal_calorie

    @property
    def should_defer_delete(self) -> bool:
        return self.env == "production" if self.dsr_defer_delete is None else self.dsr_defer_delete

    @property
    def effective_cors_origins(self) -> list[str]:
        if self.cors_allowed_origins is not None:
            return [o.strip() for o in self.cors_allowed_origins if o.strip()]
        if self.env == "production":
            return ["https://tastoria.ctslab.net"]
        return [
            "https://tastoria.ctslab.net",
            "http://localhost:8081",
            "http://127.0.0.1:8081",
            "http://localhost:19006",
        ]

    @property
    def effective_rate_limit_backend(self) -> Literal["valkey", "memory"]:
        if self.rate_limit_backend == "auto":
            return "memory" if self.login_throttle_backend == "memory" else "valkey"
        return self.rate_limit_backend

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
        if (
            not self.jwt_keys
            or any(v in _DEV_JWT_KEYS.values() for v in self.jwt_keys.values())
            or any(len(v.encode("utf-8")) < 32 for v in self.jwt_keys.values())
        ):
            bad.append("TASTORIA_JWT_KEYS")
        if self.jwt_active_kid not in self.jwt_keys:
            bad.append("TASTORIA_JWT_ACTIVE_KID")
        if (
            not self.survey_jwt_keys
            or any(
                v in _DEV_SURVEY_JWT_KEYS.values() or v in _DEV_JWT_KEYS.values()
                for v in self.survey_jwt_keys.values()
            )
            or any(len(v.encode("utf-8")) < 32 for v in self.survey_jwt_keys.values())
            or not set(self.survey_jwt_keys.values()).isdisjoint(self.jwt_keys.values())
        ):
            bad.append("TASTORIA_SURVEY_JWT_KEYS")
        if self.survey_jwt_active_kid not in self.survey_jwt_keys:
            bad.append("TASTORIA_SURVEY_JWT_ACTIVE_KID")
        if (
            not self.health_enc_keys
            or any(v in _DEV_ENC_KEYS.values() for v in self.health_enc_keys.values())
            or not all(_is_valid_b64_32(v) for v in self.health_enc_keys.values())
        ):
            bad.append("TASTORIA_HEALTH_ENC_KEYS")
        if self.health_enc_active_key_id not in self.health_enc_keys:
            bad.append("TASTORIA_HEALTH_ENC_ACTIVE_KEY_ID")
        if self.dsr_hmac_key == _DEV_HMAC or len(self.dsr_hmac_key.encode("utf-8")) < 32:
            bad.append("TASTORIA_DSR_HMAC_KEY")
        if (
            not self.training_export_hmac_key
            or self.training_export_hmac_key == _DEV_HMAC
            or len(self.training_export_hmac_key.encode("utf-8")) < 32
        ):
            bad.append("TASTORIA_TRAINING_EXPORT_HMAC_KEY")
        try:
            db_u = make_url(self.database_url)
            if (
                self.database_url == _dev_dsn()
                or db_u.password in (None, "", "tastoria", "change-me")
                or (db_u.host in ("127.0.0.1", "localhost") and db_u.username == "tastoria")
            ):
                bad.append("TASTORIA_DATABASE_URL")
        except Exception:
            bad.append("TASTORIA_DATABASE_URL")
        try:
            vk_u = urlparse(self.valkey_url)
            if not vk_u.password:
                bad.append("TASTORIA_VALKEY_URL")
        except Exception:
            bad.append("TASTORIA_VALKEY_URL")
        if self.mailer == "smtp" and not self.smtp_starttls:
            bad.append("TASTORIA_SMTP_STARTTLS")
        if "*" in self.effective_cors_origins:
            bad.append("TASTORIA_CORS_ALLOWED_ORIGINS(*)")
        if self.login_throttle_backend == "memory":
            bad.append("TASTORIA_LOGIN_THROTTLE_BACKEND(memory)")
        if self.effective_rate_limit_backend == "memory":
            bad.append("TASTORIA_RATE_LIMIT_BACKEND(memory)")
        if not self.rate_limit_enabled:
            bad.append("TASTORIA_RATE_LIMIT_ENABLED(false)")
        if bad:
            raise RuntimeError("development/unsafe settings in production: " + ", ".join(bad))


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.check_production()
    return s
