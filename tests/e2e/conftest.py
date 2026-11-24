"""Shared pytest fixtures & opaque-box helpers for Tastoria 4-tier E2E suite."""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from tests.e2e.rubric import DEFAULT_REPORT_PATH, RubricCollector

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE_URL = "http://127.0.0.1:16880"
DEFAULT_COMPOSE_PROJECT = "tastoria_e2e"
DEFAULT_PASSWORD = "matkhau-e2e-12345"

STANDARD_HOUSEHOLD_LOTS: list[tuple[str, str, float | tuple[int, str]]] = [
    ("trứng gà", "count", (10, "qua")),
    ("rau muống", "grams", 800.0),
    ("thịt ba chỉ", "grams", 600.0),
    ("thịt băm", "grams", 400.0),
    ("rau ngót", "grams", 400.0),
    ("hành lá", "grams", 150.0),
    ("bắp cải", "grams", 900.0),
    ("cà chua", "grams", 400.0),
    ("hành tím", "grams", 100.0),
    ("tỏi", "grams", 100.0),
]


def _compose_cmd(*args: str) -> list[str]:
    project = os.environ.get("TASTORIA_E2E_COMPOSE_PROJECT", DEFAULT_COMPOSE_PROJECT)
    return [
        "docker",
        "compose",
        "-p",
        project,
        "-f",
        str(REPO_ROOT / "deploy" / "docker-compose.yml"),
        "-f",
        str(REPO_ROOT / "tests" / "e2e" / "docker-compose.e2e.yml"),
        *args,
    ]


def _compose_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("POSTGRES_PASSWORD", "tastoria_e2e_pg_pass")
    return env


def unique_email(prefix: str = "e2e") -> str:
    return f"{prefix}+{int(time.time() * 1000)}+{uuid.uuid4().hex[:8]}@example.com"


def unique_idem_key(prefix: str = "e2e") -> str:
    return f"{prefix}_{uuid.uuid4().hex}"[:48]


@dataclass
class CleanPageTelemetry:
    """Collects pageerror, console.error, and unexpected HTTP >= 400 responses on a Playwright Page."""

    page_errors: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    http_5xx: list[str] = field(default_factory=list)
    http_4xx: list[str] = field(default_factory=list)
    allow_4xx_statuses: set[int] = field(default_factory=set)
    allow_4xx_url_substrings: tuple[str, ...] = ("/meal-plans/latest", "/tai-ve/")
    allow_console_substrings: tuple[str, ...] = ()
    _allowed_4xx_urls: set[str] = field(default_factory=set, repr=False)

    def attach(self, page: Page) -> None:
        page.on("pageerror", lambda err: self.page_errors.append(str(err)[:400]))

        def _on_console(msg: Any) -> None:
            if msg.type == "error":
                text = msg.text[:400]
                loc = getattr(msg, "location", None)
                loc_url = loc.get("url", "") if isinstance(loc, dict) else ""
                is_resource_4xx = "Failed to load resource" in text and "status of 4" in text
                if is_resource_4xx and (
                    (loc_url and loc_url in self._allowed_4xx_urls)
                    or any(sub in loc_url for sub in self.allow_4xx_url_substrings)
                ):
                    return
                if not any(sub in text for sub in self.allow_console_substrings):
                    self.console_errors.append(text)

        def _on_response(resp: Any) -> None:
            status = resp.status
            entry = f"{status} {resp.request.method} {resp.url}"
            if status >= 500:
                self.http_5xx.append(entry)
            elif status >= 400:
                if status in self.allow_4xx_statuses or any(sub in resp.url for sub in self.allow_4xx_url_substrings):
                    self._allowed_4xx_urls.add(resp.url)
                    return
                self.http_4xx.append(entry)

        page.on("console", _on_console)
        page.on("response", _on_response)

    def assert_clean(self, *, allow_4xx: bool = False) -> None:
        assert not self.page_errors, f"Uncaught JS pageerrors: {self.page_errors}"
        assert not self.console_errors, f"Console errors: {self.console_errors}"
        assert not self.http_5xx, f"HTTP 5xx errors: {self.http_5xx}"
        if not allow_4xx:
            assert not self.http_4xx, f"Unexpected HTTP 4xx errors: {self.http_4xx}"


class E2EHelpers:
    """Opaque-box API, DB-role, CLI, and screenshot helpers bound to the live E2E stack."""

    def __init__(self, base_url: str, raw_client: httpx.Client, api_client: httpx.Client) -> None:
        self.base_url = base_url.rstrip("/")
        self.raw = raw_client
        self.api = api_client
        self._ingredient_cache: dict[str, dict[str, Any]] = {}
        self._recipe_cache: dict[str, dict[str, Any]] = {}

    @staticmethod
    def auth_headers(token: str, *, idem: str | None = None, app_version: str | None = None) -> dict[str, str]:
        h = {"Authorization": f"Bearer {token}"}
        if idem:
            h["Idempotency-Key"] = idem
        if app_version:
            h["X-App-Version"] = app_version
        return h

    def register_user(self, email: str | None = None, password: str = DEFAULT_PASSWORD) -> dict[str, Any]:
        addr = email or unique_email("usr")
        resp = self.api.post("/auth/register", json={"email": addr, "password": password})
        assert resp.status_code == 201, f"register failed ({resp.status_code}): {resp.text}"
        data = resp.json()
        data["_email"] = addr
        data["_password"] = password
        return data

    def login_user(self, email: str, password: str = DEFAULT_PASSWORD) -> dict[str, Any]:
        resp = self.api.post("/auth/login", json={"email": email, "password": password})
        assert resp.status_code == 200, f"login failed ({resp.status_code}): {resp.text}"
        return resp.json()

    def promote_user_role(self, email: str, role: str) -> None:
        """Promote a registered user's role in Postgres via docker compose exec psql (or direct psql)."""
        assert role in {"user", "admin", "curator", "ml_operator"}, f"Unsupported role: {role}"
        sql = f"UPDATE users SET role = '{role}' WHERE email = '{email.lower()}';"
        proc = subprocess.run(
            [*_compose_cmd("exec", "-T", "postgres", "psql", "-U", "tastoria", "-d", "tastoria", "-c", sql)],
            capture_output=True,
            text=True,
            check=False,
            env=_compose_env(),
        )
        if proc.returncode != 0:
            db_url = os.environ.get("TASTORIA_E2E_DATABASE_URL")
            if db_url:
                proc2 = subprocess.run(["psql", db_url, "-c", sql], capture_output=True, text=True, check=False)
                assert proc2.returncode == 0, f"psql role promotion failed: {proc2.stderr}"
                return
            raise RuntimeError(f"Failed to promote user {email} to {role}: {proc.stderr or proc.stdout}")

    def create_staff_session(self, role: str = "ml_operator") -> dict[str, Any]:
        reg = self.register_user(email=unique_email(role))
        self.promote_user_role(reg["_email"], role)
        session = self.login_user(reg["_email"], reg["_password"])
        assert session["user"]["role"] == role
        return session

    def run_cli(self, *cli_args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run `tastoria ...` inside the `api` container (or directly if installed locally on 153)."""
        proc = subprocess.run(
            [*_compose_cmd("exec", "-T", "api", "tastoria", *cli_args)],
            capture_output=True,
            text=True,
            check=False,
            env=_compose_env(),
        )
        if proc.returncode != 0 and "no such service" in (proc.stderr or "").lower():
            proc = subprocess.run(["tastoria", *cli_args], capture_output=True, text=True, check=False)
        if check:
            assert proc.returncode == 0, f"tastoria {' '.join(cli_args)} failed ({proc.returncode}): {proc.stderr}\n{proc.stdout}"
        return proc

    def ensure_open_survey_form(self, anchors: int = 10, random_n: int = 35, seed: int = 42) -> str:
        """Open a 45-dish survey form using `tastoria survey create-form ... --yes`."""
        proc = self.run_cli(
            "survey",
            "create-form",
            "--anchors",
            str(anchors),
            "--random",
            str(random_n),
            "--seed",
            str(seed),
            "--yes",
        )
        # Extract version token from CLI JSON/text output
        out = proc.stdout.strip()
        try:
            parsed = json.loads(out)
            if isinstance(parsed, dict) and "version" in parsed:
                return str(parsed["version"])
        except json.JSONDecodeError:
            pass
        return out.splitlines()[-1].strip() if out else "unknown"

    def get_policy_version_id(self, purpose: str) -> str:
        resp = self.api.get(f"/policies/{purpose}/current")
        assert resp.status_code == 200, f"GET /policies/{purpose}/current -> {resp.status_code}: {resp.text}"
        return resp.json()["id"]

    def grant_consents(
        self,
        token: str,
        purposes: tuple[str, ...] = ("health_profile", "personalization", "photo_contribution"),
        channel: str = "onboarding",
    ) -> dict[str, Any]:
        decisions = [{"policy_version_id": self.get_policy_version_id(p), "action": "grant"} for p in purposes]
        resp = self.api.post(
            "/me/consents",
            headers=self.auth_headers(token),
            json={"channel": channel, "decisions": decisions},
        )
        assert resp.status_code == 200, f"POST /me/consents -> {resp.status_code}: {resp.text}"
        return resp.json()

    def seed_profile_and_energy(
        self,
        token: str,
        *,
        sex: str = "female",
        birth_year: int = 1995,
        height_cm: float = 158.0,
        weight_kg: float = 52.0,
        activity_level: str = "light",
        goal: str = "maintain",
        diet_code: str | None = None,
        allergen_codes: list[str] | None = None,
    ) -> dict[str, Any]:
        h = self.auth_headers(token)
        r = self.api.put(
            "/me/profile",
            headers=h,
            json={
                "sex": sex,
                "birth_year": birth_year,
                "height_cm": height_cm,
                "weight_kg": weight_kg,
                "activity_level": activity_level,
                "goal": goal,
                "adult_confirmed": False,
            },
        )
        assert r.status_code == 200, f"PUT /me/profile -> {r.status_code}: {r.text}"
        sugg = self.api.post("/me/energy-suggestion", headers=h, json={"goal": goal}).json()
        target = self.api.put(
            "/me/energy-target",
            headers=h,
            json={"kcal_target": sugg["suggested_kcal"], "kcal_source": "suggested", "goal": goal},
        )
        assert target.status_code == 200, f"PUT /me/energy-target -> {target.status_code}: {target.text}"
        if diet_code is not None:
            dr = self.api.put("/me/diet", headers=h, json={"diet_code": diet_code})
            assert dr.status_code == 200, f"PUT /me/diet -> {dr.status_code}: {dr.text}"
        if allergen_codes is not None:
            ar = self.api.put("/me/allergens", headers=h, json={"allergen_codes": allergen_codes})
            assert ar.status_code == 200, f"PUT /me/allergens -> {ar.status_code}: {ar.text}"
        return target.json()

    def resolve_ingredient(self, token: str, name_vi: str) -> dict[str, Any]:
        if name_vi in self._ingredient_cache:
            return self._ingredient_cache[name_vi]
        resp = self.api.get("/ingredients", headers=self.auth_headers(token), params={"q": name_vi, "limit": 50})
        assert resp.status_code == 200, f"GET /ingredients?q={name_vi} -> {resp.status_code}: {resp.text}"
        items = resp.json()["items"]
        exact = [it for it in items if it["name_vi"].lower() == name_vi.lower()]
        chosen = exact[0] if exact else (items[0] if items else None)
        assert chosen is not None, f"Ingredient not found in KB: {name_vi}"
        self._ingredient_cache[name_vi] = chosen
        return chosen

    def resolve_ingredient_id(self, token: str, name_vi: str) -> str:
        return self.resolve_ingredient(token, name_vi)["id"]

    def resolve_recipe_id(self, token: str, name_vi: str, slot: str | None = None) -> str:
        cache_key = f"{slot}:{name_vi}"
        if cache_key in self._recipe_cache:
            return self._recipe_cache[cache_key]["id"]
        params: dict[str, Any] = {"q": name_vi, "limit": 50}
        if slot:
            params["slot"] = slot
        resp = self.api.get("/recipes", headers=self.auth_headers(token), params=params)
        assert resp.status_code == 200, f"GET /recipes?q={name_vi} -> {resp.status_code}: {resp.text}"
        items = resp.json()["items"]
        exact = [it for it in items if it["name_vi"].lower() == name_vi.lower()]
        chosen = exact[0] if exact else (items[0] if items else None)
        assert chosen is not None, f"Recipe not found in KB: {name_vi}"
        self._recipe_cache[cache_key] = chosen
        return chosen["id"]

    def seed_pantry_lot(
        self,
        token: str,
        name_vi: str,
        *,
        grams: float | None = None,
        count: int | None = None,
        unit_code: str | None = None,
        qty_level: str | None = None,
        days_ago: float | None = None,
    ) -> dict[str, Any]:
        ing = self.resolve_ingredient(token, name_vi)
        if count is not None:
            ucode = unit_code or (ing["units"][0]["unit_code"] if ing["units"] else "qua")
            qty: dict[str, Any] = {"count": count, "unit_code": ucode}
        elif qty_level is not None:
            qty = {"qty_level": qty_level}
        else:
            val = grams if grams is not None else 500.0
            qty = {"g_min": val, "g_max": val}

        body: dict[str, Any] = {"ingredient_id": ing["id"], "quantity": qty}
        if days_ago is not None:
            body["acquired_at"] = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()

        resp = self.api.post("/pantry/lots", headers=self.auth_headers(token), json=body)
        assert resp.status_code == 201, f"POST /pantry/lots ({name_vi}) -> {resp.status_code}: {resp.text}"
        return resp.json()

    def seed_standard_household_pantry(self, token: str) -> list[dict[str, Any]]:
        lots: list[dict[str, Any]] = []
        for name_vi, kind, val in STANDARD_HOUSEHOLD_LOTS:
            if kind == "count":
                cnt, ucode = val  # type: ignore[misc]
                lots.append(self.seed_pantry_lot(token, name_vi, count=cnt, unit_code=ucode))
            else:
                lots.append(self.seed_pantry_lot(token, name_vi, grams=float(val)))
        return lots

    def create_ready_user(
        self,
        *,
        purposes: tuple[str, ...] = ("health_profile", "personalization", "photo_contribution"),
        seed_pantry: bool = True,
        diet_code: str | None = None,
        allergen_codes: list[str] | None = None,
    ) -> dict[str, Any]:
        auth = self.register_user()
        token = auth["access_token"]
        if purposes:
            self.grant_consents(token, purposes=purposes)
            if "health_profile" in purposes:
                self.seed_profile_and_energy(token, diet_code=diet_code, allergen_codes=allergen_codes)
        if seed_pantry:
            self.seed_standard_household_pantry(token)
        return auth


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.environ.get("TASTORIA_E2E_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


@pytest.fixture(scope="session")
def raw_client(base_url: str) -> httpx.Client:
    with httpx.Client(base_url=base_url, timeout=30.0, follow_redirects=False) as client:
        yield client


@pytest.fixture(scope="session")
def api_client(base_url: str) -> httpx.Client:
    with httpx.Client(base_url=f"{base_url}/api/v1", timeout=30.0, follow_redirects=False) as client:
        yield client


@pytest.fixture(scope="session")
def helpers(base_url: str, raw_client: httpx.Client, api_client: httpx.Client) -> E2EHelpers:
    return E2EHelpers(base_url, raw_client, api_client)


@pytest.fixture(scope="session")
def playwright_browser() -> Browser:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--enable-unsafe-swiftshader", "--no-sandbox"],
        )
        yield browser
        browser.close()


@pytest.fixture(scope="session")
def rubric_collector() -> RubricCollector:
    collector = RubricCollector(DEFAULT_REPORT_PATH)
    yield collector
    collector.flush()


@pytest.fixture()
def page_factory(
    playwright_browser: Browser,
) -> Callable[..., tuple[BrowserContext, Page, CleanPageTelemetry]]:
    """Create isolated BrowserContext + Page with vi-VN locale, Asia/Ho_Chi_Minh tz, and telemetry."""
    created: list[BrowserContext] = []

    def _make(
        *,
        viewport: tuple[int, int] = (390, 844),
        color_scheme: str = "light",
        reduced_motion: str = "no-preference",
        allow_4xx_statuses: set[int] | None = None,
        allow_console_substrings: tuple[str, ...] = (),
        java_script_enabled: bool = True,
    ) -> tuple[BrowserContext, Page, CleanPageTelemetry]:
        ctx = playwright_browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]},
            device_scale_factor=2 if viewport[0] <= 480 else 1,
            color_scheme=color_scheme,
            reduced_motion=reduced_motion,
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
            java_script_enabled=java_script_enabled,
        )
        created.append(ctx)
        page = ctx.new_page()
        page.set_default_timeout(20000)
        telemetry = CleanPageTelemetry(
            allow_4xx_statuses=set(allow_4xx_statuses or set()),
            allow_console_substrings=allow_console_substrings,
        )
        telemetry.attach(page)
        return ctx, page, telemetry

    yield _make

    for ctx in created:
        ctx.close()


@pytest.fixture(scope="session")
def screenshot_saver() -> Callable[[Page, str, str], tuple[Path, Path]]:
    """Save deterministic PNGs to both app/docs/screenshots/ and docs/reports/mobile-app/fig/."""
    shot_dir = Path(os.environ.get("TASTORIA_E2E_SCREENSHOT_DIR", str(REPO_ROOT / "app" / "docs" / "screenshots"))).expanduser()
    fig_dir = Path(os.environ.get("TASTORIA_E2E_REPORT_FIG_DIR", str(REPO_ROOT / "docs" / "reports" / "mobile-app" / "fig"))).expanduser()
    shot_dir.mkdir(parents=True, exist_ok=True)
    fig_dir.mkdir(parents=True, exist_ok=True)

    def _save(page: Page, app_filename: str, report_filename: str | None = None) -> tuple[Path, Path]:
        page.evaluate("() => document.fonts ? document.fonts.ready : Promise.resolve()")
        page.wait_for_timeout(350)
        p1 = shot_dir / app_filename
        p1.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(p1))
        p2 = fig_dir / (report_filename or app_filename)
        p2.parent.mkdir(parents=True, exist_ok=True)
        p2.write_bytes(p1.read_bytes())
        return p1, p2

    return _save
