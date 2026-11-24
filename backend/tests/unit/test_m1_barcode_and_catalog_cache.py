"""Unit tests for M1 BarcodeCatalog (httpx, transient-error non-caching, URL sanitization),
Catalog versioned cache, and MLOps ONNX gate for meal_calorie / dish_classifier / mushroom_classifier."""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from tastoria.modules.catalog import service as catalog_service
from tastoria.modules.catalog.schemas import RecipeView, StepView
from tastoria.modules.meal_calorie.barcode import BarcodeCatalog, _sanitize_image_url
from tastoria.modules.mlops import service as mlops_service

# ---------------------------------------------------------------- pure-Python ONNX builder for MLOps gate tests


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def _tag(field: int, wire: int) -> bytes:
    return _varint((field << 3) | wire)


def _ld(field: int, data: bytes) -> bytes:
    return _tag(field, 2) + _varint(len(data)) + data


def _vi(field: int, val: int) -> bytes:
    return _tag(field, 0) + _varint(val)


def _tensor_type_proto(dims: list[int | str]) -> bytes:
    shape_dims = b""
    for d in dims:
        if isinstance(d, int):
            shape_dims += _ld(1, _vi(1, d))
        else:
            shape_dims += _ld(1, _ld(2, d.encode()))
    return _ld(1, _vi(1, 1) + _ld(2, shape_dims))


def _value_info(name: str, dims: list[int | str]) -> bytes:
    return _ld(1, name.encode()) + _ld(2, _tensor_type_proto(dims))


def _build_classifier_onnx(path: Path, n_classes: int) -> Path:
    # Minimal valid opset-13 model: [n, 3, 224, 224] -> Identity/Reshape-free ReduceSum/Slice -> use Shape/Cast?
    # Simplest: ReduceMean(axes=[2,3]) -> [n, 3], then Pad/Slice or Gemm? Use ConstantOfShape or Pad to n_classes.
    # Actually simplest valid graph: input ['n', 3, 224, 224] -> ReduceMean(axes=[2,3], keepdims=0) -> ['n', 3],
    # and if n_classes == 3 output it directly; for n_classes > 3, Pad or Concat multiple ReduceMean!
    nodes = [
        _ld(1, b"image")
        + _ld(2, b"mean3")
        + _ld(4, b"ReduceMean")
        + _ld(5, _ld(1, b"axes") + _vi(20, 7) + _vi(8, 2) + _vi(8, 3))
        + _ld(5, _ld(1, b"keepdims") + _vi(20, 2) + _vi(3, 0)),
        _ld(1, b"mean3")
        + _ld(1, b"mean3")
        + _ld(2, b"out6")
        + _ld(4, b"Concat")
        + _ld(5, _ld(1, b"axis") + _vi(20, 2) + _vi(3, 1)),
    ]
    out_name = "out6" if n_classes == 6 else "mean3"
    if n_classes > 6:
        nodes.append(
            _ld(1, b"out6")
            + _ld(1, b"mean3")
            + _ld(2, b"out9")
            + _ld(4, b"Concat")
            + _ld(5, _ld(1, b"axis") + _vi(20, 2) + _vi(3, 1))
        )
        out_name = "out9"
    graph = (
        b"".join(_ld(1, n) for n in nodes)
        + _ld(2, b"mlops_test")
        + _ld(11, _value_info("image", ["n", 3, 224, 224]))
        + _ld(12, _value_info(out_name, ["n", n_classes]))
    )
    model = _vi(1, 8) + _ld(7, graph) + _ld(8, _ld(1, b"") + _vi(2, 13))
    path.write_bytes(model)
    return path


# ---------------------------------------------------------------- BarcodeCatalog httpx + non-caching


def test_barcode_transient_errors_not_cached_and_404_is_cached() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        bc = request.url.path.rsplit("/", 1)[-1].removesuffix(".json")
        if bc == "8930000000001":
            if calls == 1:
                raise httpx.ReadTimeout("slow network", request=request)
            if calls == 2:
                return httpx.Response(503, json={"error": "upstream down"})
            if calls == 3:
                return httpx.Response(429, json={"error": "rate limited"})
            return httpx.Response(
                200,
                json={
                    "status": 1,
                    "product": {
                        "product_name_vi": "Sữa tươi ít đường",
                        "brands": "Vinamilk",
                        "serving_size": "180 ml",
                        "serving_quantity": 180,
                        "image_front_small_url": "https://images.openfoodfacts.org/milk.jpg",
                        "nutriments": {
                            "energy-kcal_100g": 60,
                            "proteins_100g": 3.0,
                            "carbohydrates_100g": 4.8,
                            "fat_100g": 3.2,
                        },
                    },
                },
            )
        return httpx.Response(404, json={"status": 0})

    cat = BarcodeCatalog({}, miss_ttl_s=60.0)
    cat._client.close()
    cat._client = httpx.Client(transport=httpx.MockTransport(handler))

    # Calls 1, 2, 3 fail transiently -> return None and MUST NOT populate _cache
    assert cat.lookup("8930000000001") is None
    assert cat.lookup("8930000000001") is None
    assert cat.lookup("8930000000001") is None
    assert "8930000000001" not in cat._cache

    # Call 4 succeeds -> returns product and caches it (call 5 hits cache)
    prod = cat.lookup("8930000000001")
    assert prod is not None
    assert prod.product_name == "Sữa tươi ít đường"
    assert prod.image_url == "https://images.openfoodfacts.org/milk.jpg"
    assert cat.lookup("8930000000001") == prod
    assert calls == 4

    # Definitive 404 miss IS cached (only 1 network call for 2 lookups)
    assert cat.lookup("8930000000002") is None
    assert cat.lookup("8930000000002") is None
    assert calls == 5


def test_barcode_image_url_sanitization() -> None:
    assert _sanitize_image_url("https://images.openfoodfacts.org/images/products/1.jpg") is not None
    assert _sanitize_image_url("https://world.openfoodfacts.net/images/1.png") is not None
    assert _sanitize_image_url("http://images.openfoodfacts.org/1.jpg") is None
    assert _sanitize_image_url("javascript:alert(1)") is None
    assert _sanitize_image_url("data:image/png;base64,AAAA") is None
    assert _sanitize_image_url("https://evil.example/img.jpg") is None
    assert _sanitize_image_url("https://user:pass@images.openfoodfacts.org/1.jpg") is None
    assert _sanitize_image_url("https://images.openfoodfacts.org/1.jpg\nSet-Cookie: a=b") is None


# ---------------------------------------------------------------- Catalog versioned cache


def _recipe_view(name: str, slot: str) -> RecipeView:
    return RecipeView(
        id=uuid.uuid4(),
        name_vi=name,
        slot=slot,
        servings=2,
        method_code="xao",
        status="published",
        lines=(),
        steps=(StepView(1, "Nấu", "active", 10, True),),
        tag_codes=frozenset(),
        kcal_per_serving=250.0,
    )


def test_catalog_published_recipes_versioned_cache_and_invalidation(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog_service.invalidate_published_recipes_cache()

    fake_session = SimpleNamespace(
        new=set(),
        dirty=set(),
        deleted=set(),
        get_bind=lambda: SimpleNamespace(
            engine=SimpleNamespace(url=SimpleNamespace(render_as_string=lambda hide_password=True: "pg://db_a"))
        ),
    )
    other_session = SimpleNamespace(
        new=set(),
        dirty=set(),
        deleted=set(),
        get_bind=lambda: SimpleNamespace(
            engine=SimpleNamespace(url=SimpleNamespace(render_as_string=lambda hide_password=True: "pg://db_b"))
        ),
    )

    ver = [1]
    loads = 0
    views_pool = [_recipe_view("Rau muống xào", "rau"), _recipe_view("Thịt kho", "man")]

    monkeypatch.setattr(catalog_service, "_catalog_version_key", lambda s: (ver[0],))

    def fake_uncached(session, slot=None):  # noqa: ANN001, ANN202
        nonlocal loads
        loads += 1
        return [v for v in views_pool if slot is None or v.slot == slot]

    monkeypatch.setattr(catalog_service, "_published_recipes_uncached", fake_uncached)

    # First call loads and caches; second call and slot filter hit cache without re-querying.
    r1 = catalog_service.published_recipes(fake_session)  # type: ignore[arg-type]
    r2 = catalog_service.published_recipes(fake_session)  # type: ignore[arg-type]
    r_man = catalog_service.published_recipes(fake_session, slot="man")  # type: ignore[arg-type]
    assert loads == 1
    assert len(r1) == 2 and len(r_man) == 1 and r_man[0].name_vi == "Thịt kho"
    assert r1 is not r2
    r1.clear()
    assert len(catalog_service.published_recipes(fake_session)) == 2  # caller mutation cannot corrupt cache

    # Version bump invalidates cache.
    ver[0] = 2
    catalog_service.published_recipes(fake_session)  # type: ignore[arg-type]
    assert loads == 2

    # Different DB key is isolated.
    catalog_service.published_recipes(other_session)  # type: ignore[arg-type]
    assert loads == 3

    # Explicit invalidation clears cache for that DB key.
    catalog_service.invalidate_published_recipes_cache(fake_session)  # type: ignore[arg-type]
    catalog_service.published_recipes(fake_session)  # type: ignore[arg-type]
    assert loads == 4

    catalog_service.invalidate_published_recipes_cache()


# ---------------------------------------------------------------- MLOps ONNX checks for new model names


def test_mlops_onnx_checks_for_new_models(tmp_path: Path) -> None:
    p6 = _build_classifier_onnx(tmp_path / "m6.onnx", 6)
    p9 = _build_classifier_onnx(tmp_path / "m9.onnx", 9)

    assert mlops_service._onnx_checks(p9, "meal_calorie", 0) == []
    assert mlops_service._onnx_checks(p6, "dish_classifier", 0) == []
    assert mlops_service._onnx_checks(p6, "mushroom_classifier", 0) == []
    # meal_calorie requires output dim >= 5; 3-dim fails
    p3 = _build_classifier_onnx(tmp_path / "m3.onnx", 3)
    assert mlops_service._onnx_checks(p3, "meal_calorie", 0) != []


def test_catalog_cache_key_and_version_sqlite_compatibility() -> None:
    eng_a = create_engine("sqlite:///:memory:")
    eng_b = create_engine("sqlite:///:memory:")
    try:
        ddl = (
            "CREATE TABLE recipes (id TEXT PRIMARY KEY, status TEXT, updated_at TEXT);",
            "CREATE TABLE ingredients (id TEXT PRIMARY KEY, is_active INTEGER, updated_at TEXT);",
            "CREATE TABLE recipe_nutrition (recipe_id TEXT, computed_at TEXT);",
        )
        for eng, rid in ((eng_a, "11111111-1111-1111-1111-111111111111"), (eng_b, "22222222-2222-2222-2222-222222222222")):
            with eng.begin() as conn:
                for stmt in ddl:
                    conn.execute(text(stmt))
                conn.execute(
                    text("INSERT INTO recipes (id, status, updated_at) VALUES (:id, 'published', '2026-01-01')"),
                    {"id": rid},
                )
        with Session(eng_a) as sa, Session(eng_b) as sb:
            key_a = catalog_service._cache_db_key(sa)
            key_b = catalog_service._cache_db_key(sb)
            assert key_a != key_b
            assert "#"+str(id(eng_a)) in key_a
            ver_a = catalog_service._catalog_version_key(sa)
            ver_b = catalog_service._catalog_version_key(sb)
            assert ver_a[0] == 1 and ver_b[0] == 1
            assert ver_a[2] == "11111111-1111-1111-1111-111111111111"
            assert ver_b[2] == "22222222-2222-2222-2222-222222222222"
    finally:
        eng_a.dispose()
        eng_b.dispose()


def test_barcode_non_finite_stream_cap_basis_and_503(tmp_path: Path) -> None:
    from tastoria.core.errors import ApiError, ProblemCode
    from tastoria.modules.meal_calorie.barcode import BarcodeUpstreamError, _float_or_none
    from tastoria.modules.meal_calorie.service import MealCalorieDeps, lookup_barcode

    # P1-11: reject NaN, Inf, bool, negative, and implausible values > 10000
    assert _float_or_none("NaN") is None
    assert _float_or_none(float("inf")) is None
    assert _float_or_none(float("-inf")) is None
    assert _float_or_none(True) is None
    assert _float_or_none(-5.0) is None
    assert _float_or_none(10001.0) is None
    assert _float_or_none(250.5) == 250.5

    # P1-13: consistent serving vs 100g basis (no mixed truthy `or` across bases when 0 is present)
    def basis_handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": 1,
                "product": {
                    "product_name_vi": "Nước uống không calo",
                    "serving_size": "250 ml",
                    "serving_quantity": 250,
                    "nutriments": {
                        "energy-kcal_serving": 0,
                        "proteins_serving": 0,
                        "carbohydrates_serving": 0,
                        "fat_serving": 0,
                        "energy-kcal_100g": 45,
                        "proteins_100g": 2.0,
                        "carbohydrates_100g": 10.0,
                        "fat_100g": 1.0,
                    },
                },
            },
        )

    cat = BarcodeCatalog({}, miss_ttl_s=60.0)
    cat._client.close()
    cat._client = httpx.Client(transport=httpx.MockTransport(basis_handler))
    prod = cat.lookup("8930000000011")
    assert prod is not None
    assert (prod.kcal_per_serving, prod.protein_g_per_serving, prod.carbs_g_per_serving, prod.fat_g_per_serving) == (
        0.0,
        0.0,
        0.0,
        0.0,
    )

    # P1-11: stream cap > 256 KB
    big_payload = b'{"status":1,"product":{"product_name":"' + (b"A" * (300 * 1024)) + b'"}}'

    def big_handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=big_payload)

    cat._client.close()
    cat._client = httpx.Client(transport=httpx.MockTransport(big_handler))
    with pytest.raises(BarcodeUpstreamError):
        cat.lookup("8930000000022", raise_on_transient=True)

    # P1-11: transient OFF 503 raises 503 temporarily_unavailable + Retry-After from service.lookup_barcode
    def err_handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"err": "down"})

    cat._client.close()
    cat._client = httpx.Client(transport=httpx.MockTransport(err_handler))
    deps = MealCalorieDeps(
        model_dir=tmp_path,
        kb_dir=tmp_path,
        kb_processed_dir=tmp_path,
        barcode_catalog=cat,
    )
    with pytest.raises(ApiError) as exc:
        lookup_barcode(deps, barcode="8930000000033")
    assert exc.value.status == 503
    assert exc.value.code == ProblemCode.temporarily_unavailable
    assert "Retry-After" in exc.value.headers

    # P2-2: BarcodeCatalog.reopen() restores usable client after close()
    cat.close()
    assert cat._client.is_closed
    cat.reopen()
    assert not cat._client.is_closed
    cat.close()


def test_mlops_version_and_path_traversal_rejected(tmp_path: Path) -> None:
    from sqlalchemy import create_engine

    from tastoria.modules.mlops.schemas import MlopsError

    eng = create_engine("sqlite:///:memory:")
    try:
        art = tmp_path / "m.onnx"
        art.write_bytes(b"onnx")
        with Session(eng) as sess:
            for bad_ver in ("../escape", "../../etc", "v/1", "..", ".", "bad space", ""):
                with pytest.raises(MlopsError, match="phiên bản"):
                    mlops_service.register(
                        sess,
                        storage_dir=tmp_path,
                        name="ranker",
                        version=bad_ver,
                        artifact=art,
                        metrics={},
                        preprocess_version=None,
                        class_codes=None,
                    )
    finally:
        eng.dispose()
