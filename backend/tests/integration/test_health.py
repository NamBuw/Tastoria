from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert len(r.headers["x-request-id"]) >= 8


def test_request_id_is_echoed_when_well_formed(client: TestClient) -> None:
    r = client.get("/healthz", headers={"X-Request-ID": "abc12345-req"})
    assert r.headers["x-request-id"] == "abc12345-req"
    r = client.get("/healthz", headers={"X-Request-ID": "bad id with spaces"})
    assert r.headers["x-request-id"] != "bad id with spaces"


def test_readyz_ok(client: TestClient) -> None:
    r = client.get("/readyz")
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "ready", "checks": {"database": "ok", "valkey": "ok", "models": "ok"}}


def test_readyz_reports_valkey_down(make_app, clean_db) -> None:
    app = make_app(valkey_url="redis://127.0.0.1:1/0")
    with TestClient(app) as c:
        r = c.get("/readyz")
    assert r.status_code == 503
    assert r.json()["checks"]["valkey"] == "fail"
    assert r.json()["checks"]["database"] == "ok"
    assert "retry-after" in r.headers


def test_unknown_route_is_problem_json(client: TestClient) -> None:
    r = client.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["code"] == "not_found"
    assert body["type"] == "https://tastoria.ctslab.net/problems/not_found"
    assert body["request_id"] == r.headers["x-request-id"]


def test_old_app_version_is_rejected(make_app, clean_db) -> None:
    app = make_app(min_app_version="1.2.0")
    with TestClient(app) as c:
        assert c.get("/api/v1/nothing", headers={"X-App-Version": "1.1.9"}).json()["code"] == "app_too_old"
        assert c.get("/api/v1/nothing", headers={"X-App-Version": "1.2.0"}).status_code == 404


def test_readyz_fails_closed_when_check_missing_and_metrics_exposed(make_app, clean_db, client: TestClient) -> None:
    # 1. Fail-closed readiness when any READINESS_CHECKS entry is removed or errors
    app = make_app()
    del app.state.readiness_checks["models"]
    with TestClient(app) as c:
        r = c.get("/readyz")
    assert r.status_code == 503
    assert r.json() == {"status": "not_ready", "checks": {"database": "ok", "valkey": "ok", "models": "fail"}}

    # 2. /metrics exposes Prometheus counters & scan queue depth while staying hidden from OpenAPI schema
    assert "/metrics" not in client.app.openapi()["paths"]
    m = client.get("/metrics")
    assert m.status_code == 200
    assert m.headers["content-type"].startswith("text/plain")
    assert "tastoria_http_requests_total" in m.text
    assert "tastoria_scan_queue_depth" in m.text


def test_production_disables_openapi_and_docs(make_app, clean_db) -> None:
    prod_app = make_app(env="production")
    assert prod_app.openapi_url is None and prod_app.docs_url is None
    with TestClient(prod_app) as c:
        assert c.get("/api/v1/openapi.json").status_code == 404
        assert c.get("/api/v1/docs").status_code == 404
        assert c.get("/healthz").status_code == 200
