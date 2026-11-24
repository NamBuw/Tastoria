"""Packaged-product barcode nutrition lookup (local VN catalog + Open Food Facts v2 API)."""

from __future__ import annotations

import json
import math
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import yaml

BARCODE_RE = re.compile(r"^[0-9]{8,14}$")
OFF_ENDPOINT = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
OFF_FIELDS = "product_name,product_name_vi,brands,serving_size,serving_quantity,nutriments,image_front_small_url"
USER_AGENT = "TastoriaApp/1.0 (https://tastoria.ctslab.net)"
_ALLOWED_IMAGE_HOSTS = ("openfoodfacts.org", "openfoodfacts.net")
MAX_NUTRIENT_VALUE = 10_000.0
MAX_OFF_BYTES = 256 * 1024
LOCAL_CATALOG_SOURCE_VI = "Danh mục nhãn thực phẩm Mỹ Vị"


class BarcodeUpstreamError(RuntimeError):
    """Raised when an upstream barcode provider fails transiently (timeout, 429, 5xx, oversized body)."""


@dataclass(frozen=True)
class BarcodeProduct:
    barcode: str
    product_name: str
    brand: str | None
    serving_size: str | None
    serving_g: float | None
    kcal_per_serving: float | None
    protein_g_per_serving: float | None
    carbs_g_per_serving: float | None
    fat_g_per_serving: float | None
    fiber_g_per_serving: float | None
    kcal_per_100g: float | None
    protein_g_per_100g: float | None
    carbs_g_per_100g: float | None
    fat_g_per_100g: float | None
    fiber_g_per_100g: float | None
    source: str
    image_url: str | None = None


def validate_barcode(raw: str) -> str:
    cleaned = raw.strip()
    if not BARCODE_RE.match(cleaned):
        raise ValueError(f"Mã vạch phải gồm 8 đến 14 chữ số (nhận {raw!r}).")
    return cleaned


def _float_or_none(v: object) -> float | None:
    if v is None or isinstance(v, bool) or v == "":
        return None
    try:
        x = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or x < 0.0 or x > MAX_NUTRIENT_VALUE:
        return None
    return x


def _r1(v: float | None) -> float | None:
    return round(v, 1) if v is not None else None


def _sanitize_image_url(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    url = raw.strip()
    if not url or len(url) > 512 or any(ch.isspace() or ord(ch) < 32 for ch in url):
        return None
    parts = urlsplit(url)
    if parts.scheme.lower() != "https" or not parts.hostname or parts.username or parts.password:
        return None
    host = parts.hostname.lower().rstrip(".")
    if not any(host == domain or host.endswith("." + domain) for domain in _ALLOWED_IMAGE_HOSTS):
        return None
    return url


class BarcodeCatalog:
    """Thread-safe local VN barcode lookup + Open Food Facts fallback with pooled httpx and TTL LRU cache."""

    @staticmethod
    def _make_client() -> httpx.Client:
        return httpx.Client(
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            timeout=httpx.Timeout(connect=2.0, read=4.0, write=2.0, pool=2.0),
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        )

    def __init__(
        self,
        local_items: dict[str, BarcodeProduct],
        *,
        cache_size: int = 512,
        hit_ttl_s: float = 3600.0,
        miss_ttl_s: float = 300.0,
    ) -> None:
        self.local_items = local_items
        self._cache: OrderedDict[str, tuple[float, BarcodeProduct | None]] = OrderedDict()
        self._cache_size = cache_size
        self._hit_ttl_s = hit_ttl_s
        self._miss_ttl_s = miss_ttl_s
        self._lock = threading.Lock()
        self._tl = threading.local()
        self._client = self._make_client()

    def reopen(self) -> None:
        with self._lock:
            if self._client.is_closed:
                self._client = self._make_client()

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _product_from_row(row: dict[str, object]) -> BarcodeProduct | None:
        raw_bc = row.get("barcode")
        if raw_bc is None:
            return None
        bc = str(raw_bc).strip()
        if not BARCODE_RE.match(bc):
            return None
        raw_name = row.get("name_vi") or row.get("name") or row.get("product_name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            return None
        sg = _float_or_none(row.get("serving_g"))
        kcal_s = _float_or_none(row.get("kcal_per_serving"))
        prot_s = _float_or_none(row.get("protein_g_per_serving"))
        carb_s = _float_or_none(row.get("carbs_g_per_serving"))
        fat_s = _float_or_none(row.get("fat_g_per_serving"))
        fib_s = _float_or_none(row.get("fiber_g_per_serving"))
        scale = (100.0 / sg) if (sg and sg > 0.0) else None

        kcal_100 = _float_or_none(row.get("kcal_per_100g"))
        prot_100 = _float_or_none(row.get("protein_g_per_100g"))
        carb_100 = _float_or_none(row.get("carbs_g_per_100g"))
        fat_100 = _float_or_none(row.get("fat_g_per_100g"))
        fib_100 = _float_or_none(row.get("fiber_g_per_100g"))
        if kcal_100 is None and kcal_s is not None and scale:
            kcal_100 = kcal_s * scale
        if prot_100 is None and prot_s is not None and scale:
            prot_100 = prot_s * scale
        if carb_100 is None and carb_s is not None and scale:
            carb_100 = carb_s * scale
        if fat_100 is None and fat_s is not None and scale:
            fat_100 = fat_s * scale
        if fib_100 is None and fib_s is not None and scale:
            fib_100 = fib_s * scale

        raw_src = str(row.get("source") or "").strip()
        source = LOCAL_CATALOG_SOURCE_VI if (not raw_src or raw_src == "Tastoria VN Label Catalog") else raw_src
        brand = row.get("brand")
        serving_size = row.get("serving_size")
        return BarcodeProduct(
            barcode=bc,
            product_name=raw_name.strip(),
            brand=str(brand).strip() if isinstance(brand, str) and brand.strip() else None,
            serving_size=str(serving_size).strip() if isinstance(serving_size, str) and serving_size.strip() else None,
            serving_g=sg,
            kcal_per_serving=_r1(kcal_s),
            protein_g_per_serving=_r1(prot_s),
            carbs_g_per_serving=_r1(carb_s),
            fat_g_per_serving=_r1(fat_s),
            fiber_g_per_serving=_r1(fib_s),
            kcal_per_100g=_r1(kcal_100),
            protein_g_per_100g=_r1(prot_100),
            carbs_g_per_100g=_r1(carb_100),
            fat_g_per_100g=_r1(fat_100),
            fiber_g_per_100g=_r1(fib_100),
            source=source,
            image_url=_sanitize_image_url(row.get("image_url")),
        )

    @classmethod
    def from_kb_dir(cls, kb_dir: Path) -> BarcodeCatalog:
        kb_dir = Path(kb_dir)
        items: dict[str, BarcodeProduct] = {}
        exp_path = kb_dir / "vn_barcodes_expanded.json"
        if exp_path.is_file():
            exp_doc = json.loads(exp_path.read_text(encoding="utf-8")) or {}
            for row in exp_doc.get("products") or []:
                if isinstance(row, dict):
                    prod = cls._product_from_row(row)
                    if prod is not None:
                        items[prod.barcode] = prod
        path = kb_dir / "vn_barcodes.yaml"
        if path.is_file():
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for row in doc.get("products") or []:
                if isinstance(row, dict):
                    prod = cls._product_from_row(row)
                    if prod is not None:
                        items[prod.barcode] = prod
        return cls(items)

    def _fetch_openfoodfacts(self, barcode: str, *, timeout: float = 4.0) -> BarcodeProduct | None:
        self._tl.transient = False
        url = OFF_ENDPOINT.format(barcode=barcode)
        req_timeout = httpx.Timeout(
            connect=min(2.0, timeout),
            read=timeout,
            write=min(2.0, timeout),
            pool=min(2.0, timeout),
        )
        try:
            with self._client.stream("GET", url, params={"fields": OFF_FIELDS}, timeout=req_timeout) as resp:
                if resp.status_code == 404:
                    return None
                if resp.status_code != 200:
                    # 429 / 5xx / redirects / unexpected statuses must not be negative-cached.
                    self._tl.transient = True
                    return None
                raw_cl = resp.headers.get("content-length")
                if raw_cl is not None:
                    try:
                        if int(raw_cl) > MAX_OFF_BYTES:
                            self._tl.transient = True
                            return None
                    except ValueError:
                        pass
                buf = bytearray()
                for chunk in resp.iter_bytes():
                    buf.extend(chunk)
                    if len(buf) > MAX_OFF_BYTES:
                        self._tl.transient = True
                        return None
        except httpx.HTTPError:
            self._tl.transient = True
            return None
        try:
            data = json.loads(bytes(buf))
        except (ValueError, UnicodeDecodeError):
            self._tl.transient = True
            return None
        if not isinstance(data, dict) or data.get("status") != 1:
            return None
        p = data.get("product") or {}
        if not isinstance(p, dict):
            return None
        nut = p.get("nutriments") or {}
        if not isinstance(nut, dict):
            nut = {}
        kcal_100 = _float_or_none(nut.get("energy-kcal_100g"))
        if kcal_100 is None:
            kj_100 = _float_or_none(nut.get("energy_100g"))
            if kj_100 is not None:
                kcal_100 = kj_100 / 4.184
        kcal_s = _float_or_none(nut.get("energy-kcal_serving"))
        if kcal_100 is None and kcal_s is None:
            return None

        prot_100 = _float_or_none(nut.get("proteins_100g"))
        carb_100 = _float_or_none(nut.get("carbohydrates_100g"))
        fat_100 = _float_or_none(nut.get("fat_100g"))
        fib_100 = _float_or_none(nut.get("fiber_100g"))
        sg = _float_or_none(p.get("serving_quantity"))

        prot_s = _float_or_none(nut.get("proteins_serving"))
        carb_s = _float_or_none(nut.get("carbohydrates_serving"))
        fat_s = _float_or_none(nut.get("fat_serving"))
        fib_s = _float_or_none(nut.get("fiber_serving"))
        if sg and sg > 0.0:
            factor = sg / 100.0
            if kcal_s is None and kcal_100 is not None:
                kcal_s = kcal_100 * factor
            if prot_s is None and prot_100 is not None:
                prot_s = prot_100 * factor
            if carb_s is None and carb_100 is not None:
                carb_s = carb_100 * factor
            if fat_s is None and fat_100 is not None:
                fat_s = fat_100 * factor
            if fib_s is None and fib_100 is not None:
                fib_s = fib_100 * factor

        name = str(p.get("product_name_vi") or p.get("product_name") or "").strip()
        if not name:
            return None

        return BarcodeProduct(
            barcode=barcode,
            product_name=name,
            brand=str(p.get("brands")).strip() if p.get("brands") else None,
            serving_size=str(p.get("serving_size")).strip() if p.get("serving_size") else None,
            serving_g=_r1(sg),
            kcal_per_serving=_r1(kcal_s),
            protein_g_per_serving=_r1(prot_s),
            carbs_g_per_serving=_r1(carb_s),
            fat_g_per_serving=_r1(fat_s),
            fiber_g_per_serving=_r1(fib_s),
            kcal_per_100g=_r1(kcal_100),
            protein_g_per_100g=_r1(prot_100),
            carbs_g_per_100g=_r1(carb_100),
            fat_g_per_100g=_r1(fat_100),
            fiber_g_per_100g=_r1(fib_100),
            source="Open Food Facts",
            image_url=_sanitize_image_url(p.get("image_front_small_url")),
        )

    def lookup(
        self, raw_barcode: str, *, allow_remote: bool = True, raise_on_transient: bool = False
    ) -> BarcodeProduct | None:
        barcode = validate_barcode(raw_barcode)
        if barcode in self.local_items:
            return self.local_items[barcode]
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(barcode)
            if cached is not None:
                expires_at, product = cached
                if expires_at > now:
                    self._cache.move_to_end(barcode)
                    return product
                del self._cache[barcode]
        if not allow_remote:
            return None
        self._tl.transient = False
        fetched = self._fetch_openfoodfacts(barcode)
        if fetched is None and getattr(self._tl, "transient", False):
            if raise_on_transient:
                raise BarcodeUpstreamError(f"OpenFoodFacts lookup temporarily unavailable for {barcode}")
            return None
        ttl = self._hit_ttl_s if fetched is not None else self._miss_ttl_s
        expires_at = time.monotonic() + ttl
        with self._lock:
            self._cache[barcode] = (expires_at, fetched)
            self._cache.move_to_end(barcode)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return fetched
