"""Shared pytest fixtures, rate-limit-safe user pools, and opaque-box helpers for Tastoria E2E."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

DEFAULT_BASE_URL = "http://127.0.0.1:6880"
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


def unique_email(prefix: str = "e2e") -> str:
    return f"{prefix}+{int(time.time() * 1000)}+{uuid.uuid4().hex[:8]}@example.com"


def unique_idem_key(prefix: str = "e2e") -> str:
    return f"{prefix}_{uuid.uuid4().hex}"[:48]


def _pool_cache_path(base_url: str) -> Path:
    digest = hashlib.sha256(base_url.rstrip("/").encode("utf-8")).hexdigest()[:12]
    tmpdir = Path(os.environ.get("TMPDIR") or "/tmp")
    return tmpdir / f"tastoria_e2e_user_pool_{digest}.json"


def _load_pool(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save_pool(path: Path, pool: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(pool, fh, indent=2, sort_keys=True)
    finally:
        os.chmod(path, 0o600)


@dataclass
class CleanPageTelemetry:
    """Captures console.error, pageerror, CSP securitypolicyviolation, and HTTP 4xx/5xx on Playwright pages."""

    page_errors: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    csp_violations: list[dict[str, Any]] = field(default_factory=list)
    http_5xx: list[str] = field(default_factory=list)
    http_4xx: list[str] = field(default_factory=list)
    allow_4xx_statuses: set[int] = field(default_factory=set)
    allow_4xx_url_substrings: tuple[str, ...] = ("/meal-plans/latest", "/tai-ve/", "/khong-ton-tai")
    allow_console_substrings: tuple[str, ...] = ()
    _allowed_4xx_urls: set[str] = field(default_factory=set, repr=False)

    def attach(self, context: BrowserContext, page: Page) -> None:
        context.add_init_script(
            """
            window.__tastoriaCspViolations = [];
            document.addEventListener('securitypolicyviolation', (ev) => {
              window.__tastoriaCspViolations.push({
                violatedDirective: ev.violatedDirective || '',
                effectiveDirective: ev.effectiveDirective || '',
                blockedURI: ev.blockedURI || '',
                sourceFile: ev.sourceFile || '',
                lineNumber: ev.lineNumber || 0
              });
            });
            """
        )
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
                if (
                    status in self.allow_4xx_statuses
                    or any(sub in resp.url for sub in self.allow_4xx_url_substrings)
                    or (status == 401 and "/api/v1/auth/refresh" in resp.url)
                ):
                    self._allowed_4xx_urls.add(resp.url)
                    return
                self.http_4xx.append(entry)

        page.on("console", _on_console)
        page.on("response", _on_response)

    def collect_csp(self, page: Page) -> list[dict[str, Any]]:
        try:
            items = page.evaluate("() => window.__tastoriaCspViolations || []")
            if isinstance(items, list):
                self.csp_violations = items
        except Exception:  # noqa: BLE001
            pass
        return self.csp_violations

    def assert_clean(self, page: Page | None = None, *, allow_4xx: bool = False) -> None:
        if page is not None:
            self.collect_csp(page)
        assert not self.page_errors, f"Uncaught JS pageerrors: {self.page_errors}"
        assert not self.console_errors, f"Console errors: {self.console_errors}"
        assert not self.csp_violations, f"CSP securitypolicyviolation events: {self.csp_violations}"
        assert not self.http_5xx, f"HTTP 5xx errors: {self.http_5xx}"
        if not allow_4xx:
            assert not self.http_4xx, f"Unexpected HTTP 4xx errors: {self.http_4xx}"


class E2EHelpers:
    """Opaque-box HTTP API helpers for Tastoria 4-tier E2E suite."""

    def __init__(
        self,
        base_url: str,
        raw_client: httpx.Client,
        api_client: httpx.Client,
        web_client_factory: Callable[[], httpx.Client],
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.raw = raw_client
        self.api = api_client
        self.web_client_factory = web_client_factory
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

    @staticmethod
    def create_idempotency_key(prefix: str = "e2e") -> str:
        return unique_idem_key(prefix)

    def register_user(
        self,
        email: str | None = None,
        password: str = DEFAULT_PASSWORD,
        *,
        web_client: httpx.Client | None = None,
    ) -> dict[str, Any]:
        addr = email or unique_email("usr")
        client = web_client or self.api
        resp = client.post("/auth/register", json={"email": addr, "password": password})
        assert resp.status_code == 201, f"register failed ({resp.status_code}): {resp.text}"
        data = resp.json()
        data["_email"] = addr
        data["_password"] = password
        data["_set_cookie"] = resp.headers.get_list("set-cookie")
        return data

    def login_user(
        self,
        email: str,
        password: str = DEFAULT_PASSWORD,
        *,
        web_client: httpx.Client | None = None,
    ) -> dict[str, Any]:
        client = web_client or self.api
        resp = client.post("/auth/login", json={"email": email, "password": password})
        assert resp.status_code == 200, f"login failed ({resp.status_code}): {resp.text}"
        data = resp.json()
        data["_set_cookie"] = resp.headers.get_list("set-cookie")
        return data

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
        sugg_resp = self.api.post("/me/energy-suggestion", headers=h, json={"goal": goal})
        assert sugg_resp.status_code == 200, f"POST /me/energy-suggestion -> {sugg_resp.status_code}: {sugg_resp.text}"
        sugg = sugg_resp.json()
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
        assert chosen is not None, f"Ingredient not found in catalog: {name_vi}"
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
        assert chosen is not None, f"Recipe not found in catalog: {name_vi}"
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

    def list_all_pantry_lots(
        self,
        token: str,
        *,
        sort: str = "urgency",
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Paginate through all /pantry/lots pages via next_cursor."""
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            params: dict[str, Any] = {"sort": sort}
            if limit is not None:
                params["limit"] = limit
            if cursor is not None:
                params["cursor"] = cursor
            resp = self.api.get("/pantry/lots", headers=self.auth_headers(token), params=params)
            assert resp.status_code == 200, f"GET /pantry/lots -> {resp.status_code}: {resp.text}"
            body = resp.json()
            items.extend(body.get("items", []))
            nxt = body.get("next_cursor")
            if not nxt:
                break
            assert nxt not in seen_cursors, f"Pagination loop detected on /pantry/lots cursor={nxt}"
            seen_cursors.add(nxt)
            cursor = nxt
        return items

    def seed_standard_household_pantry(self, token: str) -> list[dict[str, Any]]:
        lots: list[dict[str, Any]] = []
        for name_vi, kind, val in STANDARD_HOUSEHOLD_LOTS:
            if kind == "count":
                cnt, ucode = val  # type: ignore[misc]
                lots.append(self.seed_pantry_lot(token, name_vi, count=cnt, unit_code=ucode))
            else:
                lots.append(self.seed_pantry_lot(token, name_vi, grams=float(val)))
        return lots

    def submit_and_poll_scan(
        self,
        token: str,
        image_bytes: bytes,
        *,
        filename: str = "scan.jpg",
        content_type: str = "image/jpeg",
        mode: str = "fridge",
        contribute: bool = False,
        timeout_s: float = 45.0,
    ) -> dict[str, Any]:
        idem = self.create_idempotency_key("scan")
        resp = self.api.post(
            "/scans",
            headers=self.auth_headers(token, idem=idem),
            data={"mode": mode, "contribute": str(contribute).lower()},
            files=[("images", (filename, image_bytes, content_type))],
        )
        assert resp.status_code == 202, f"POST /scans -> {resp.status_code}: {resp.text}"
        scan_id = resp.json()["id"]

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            poll = self.api.get(f"/scans/{scan_id}", headers=self.auth_headers(token), params={"wait": 10})
            assert poll.status_code == 200, f"GET /scans/{scan_id} -> {poll.status_code}: {poll.text}"
            body = poll.json()
            if body["status"] not in ("queued", "processing"):
                return body
            time.sleep(0.5)
        raise AssertionError(f"Scan {scan_id} timed out after {timeout_s}s")

    def create_ready_user(
        self,
        *,
        purposes: tuple[str, ...] = ("health_profile", "personalization", "photo_contribution"),
        seed_pantry: bool = True,
        diet_code: str | None = None,
        allergen_codes: list[str] | None = None,
        web_client: httpx.Client | None = None,
    ) -> dict[str, Any]:
        auth = self.register_user(web_client=web_client)
        token = auth["access_token"]
        if purposes:
            self.grant_consents(token, purposes=purposes)
            if "health_profile" in purposes:
                self.seed_profile_and_energy(token, diet_code=diet_code, allergen_codes=allergen_codes)
        if seed_pantry:
            self.seed_standard_household_pantry(token)
        return auth

    def get_or_create_pooled_user(
        self,
        role: str,
        *,
        consented: bool = False,
        seed_pantry: bool = False,
        web_client: httpx.Client | None = None,
    ) -> dict[str, Any]:
        """Return a rate-limit-safe persistent pooled account (login first, register only on miss/401)."""
        pool_path = _pool_cache_path(self.base_url)
        pool = _load_pool(pool_path)
        entry = pool.get(role)
        client = web_client or self.api

        data: dict[str, Any] | None = None
        if isinstance(entry, dict) and entry.get("email") and entry.get("password"):
            login_resp = client.post(
                "/auth/login",
                json={"email": entry["email"], "password": entry["password"]},
            )
            if login_resp.status_code == 200:
                data = login_resp.json()
                data["_email"] = entry["email"]
                data["_password"] = entry["password"]
                data["_set_cookie"] = login_resp.headers.get_list("set-cookie")
                data["_from_cache"] = True

        if data is None:
            data = self.register_user(
                email=unique_email(f"pool_{role}"),
                password=DEFAULT_PASSWORD,
                web_client=web_client,
            )
            data["_from_cache"] = False
            pool[role] = {"email": data["_email"], "password": data["_password"]}
            _save_pool(pool_path, pool)

        token = data["access_token"]
        if consented:
            cons_resp = self.api.get("/me/consents", headers=self.auth_headers(token))
            assert cons_resp.status_code == 200
            states = {it["purpose_code"]: it["state"] for it in cons_resp.json().get("items", [])}
            needed = tuple(
                p for p in ("health_profile", "personalization", "photo_contribution") if states.get(p) != "granted"
            )
            if needed:
                self.grant_consents(token, purposes=needed)

            prof_resp = self.api.get("/me/profile", headers=self.auth_headers(token))
            assert prof_resp.status_code == 200
            prof = prof_resp.json()
            if prof.get("kcal_target") is None or prof.get("height_cm") is None:
                self.seed_profile_and_energy(token)

        if seed_pantry:
            in_stock_lots = [
                it for it in self.list_all_pantry_lots(token) if it.get("status") == "in_stock"
            ]
            if len(in_stock_lots) < 10:
                self.seed_standard_household_pantry(token)

        return data


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
def web_client_factory(base_url: str) -> Callable[[], httpx.Client]:
    clients: list[httpx.Client] = []
    is_loopback_http = base_url.startswith(("http://127.0.0.1", "http://localhost"))

    def _make() -> httpx.Client:
        c: httpx.Client

        def _allow_loopback_secure_cookies(_resp: httpx.Response) -> None:
            if not is_loopback_http:
                return
            for cookie in c.cookies.jar:
                if cookie.domain in ("127.0.0.1", "localhost"):
                    cookie.secure = False

        c = httpx.Client(
            base_url=f"{base_url}/api/v1",
            timeout=30.0,
            follow_redirects=False,
            headers={"X-Client-Platform": "web"},
            event_hooks={"response": [_allow_loopback_secure_cookies]} if is_loopback_http else None,
        )
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.close()


@pytest.fixture(scope="session")
def helpers(
    base_url: str,
    raw_client: httpx.Client,
    api_client: httpx.Client,
    web_client_factory: Callable[[], httpx.Client],
) -> E2EHelpers:
    return E2EHelpers(base_url, raw_client, api_client, web_client_factory)


@pytest.fixture(scope="session")
def session_native_user(helpers: E2EHelpers) -> dict[str, Any]:
    """Rate-limit-safe reusable native user (no consents/pantry seeded)."""
    return helpers.get_or_create_pooled_user("native", consented=False, seed_pantry=False)


@pytest.fixture(scope="session")
def session_web_user(helpers: E2EHelpers, web_client_factory: Callable[[], httpx.Client]) -> tuple[dict[str, Any], httpx.Client]:
    """Rate-limit-safe reusable web cookie user + isolated cookie-jar httpx.Client."""
    wc = web_client_factory()
    auth = helpers.get_or_create_pooled_user("auth_lifecycle", consented=False, seed_pantry=False, web_client=wc)
    return auth, wc


@pytest.fixture(scope="session")
def session_consented_user(helpers: E2EHelpers) -> dict[str, Any]:
    """Rate-limit-safe reusable user with consents, body profile, energy target, and household pantry."""
    return helpers.get_or_create_pooled_user("consented", consented=True, seed_pantry=True)


@pytest.fixture(scope="session")
def pooled_auth_lifecycle_user(helpers: E2EHelpers) -> dict[str, Any]:
    """Rate-limit-safe pooled account for login/refresh/logout-all/consent-withdraw tests."""
    return helpers.get_or_create_pooled_user("auth_lifecycle", consented=False, seed_pantry=False)


@pytest.fixture(scope="session")
def pooled_burst_user(helpers: E2EHelpers) -> dict[str, Any]:
    """Rate-limit-safe pooled account reserved for user-scoped 429 burst tests (T2_CAL_07, T2_SCAN_05)."""
    return helpers.get_or_create_pooled_user("auth_lifecycle", consented=False, seed_pantry=False)


@pytest.fixture()
def fresh_user_factory(helpers: E2EHelpers) -> Callable[..., dict[str, Any]]:
    """Create a fresh isolated user ONLY for destructive/lifecycle or burst rate-limit tests."""

    def _create(
        *,
        consented: bool = False,
        seed_pantry: bool = False,
        diet_code: str | None = None,
        allergen_codes: list[str] | None = None,
        web_client: httpx.Client | None = None,
    ) -> dict[str, Any]:
        if consented:
            return helpers.create_ready_user(
                seed_pantry=seed_pantry,
                diet_code=diet_code,
                allergen_codes=allergen_codes,
                web_client=web_client,
            )
        return helpers.register_user(web_client=web_client)

    return _create


@pytest.fixture(scope="session")
def browser_instance() -> Browser:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--enable-unsafe-swiftshader", "--no-sandbox"],
        )
        yield browser
        browser.close()


@pytest.fixture()
def page_factory(
    browser_instance: Browser,
) -> Callable[..., tuple[BrowserContext, Page, CleanPageTelemetry]]:
    """Create isolated Playwright BrowserContext + Page capturing console, pageerror, and CSP violations."""
    created: list[BrowserContext] = []

    def _make(
        *,
        viewport: tuple[int, int] = (1440, 900),
        color_scheme: str = "light",
        reduced_motion: str = "no-preference",
        allow_4xx_statuses: set[int] | None = None,
        allow_console_substrings: tuple[str, ...] = (),
        java_script_enabled: bool = True,
    ) -> tuple[BrowserContext, Page, CleanPageTelemetry]:
        ctx = browser_instance.new_context(
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
        telemetry.attach(ctx, page)
        return ctx, page, telemetry

    yield _make

    for ctx in created:
        ctx.close()
