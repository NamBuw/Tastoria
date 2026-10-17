"""Every implemented operation is in docs/api/openapi-v1.yaml with the same method, path and operationId, and every
field the backend puts in a 2xx JSON body is declared by the contract's schema for that response."""

from __future__ import annotations

import yaml
from conftest import REPO_ROOT

METHODS = {"get", "post", "put", "patch", "delete"}


def _contract() -> dict:
    return yaml.safe_load((REPO_ROOT / "docs/api/openapi-v1.yaml").read_text(encoding="utf-8"))


def _ops(paths: dict, prefix: str = "") -> dict[tuple[str, str], str]:
    return {
        (method.upper(), path.removeprefix(prefix)): op["operationId"]
        for path, item in paths.items()
        for method, op in item.items()
        if method in METHODS
    }


def _resolve(doc: dict, schema: dict) -> dict:
    while "$ref" in schema:
        node = doc
        for part in schema["$ref"].removeprefix("#/").split("/"):
            node = node[part]
        schema = node
    return schema


def _props(doc: dict, schema: dict, depth: int = 0) -> dict[str, dict]:
    """Property name -> schema, merging allOf/anyOf/oneOf branches."""
    schema = _resolve(doc, schema)
    out: dict[str, dict] = {}
    for key in ("allOf", "anyOf", "oneOf"):
        for sub in schema.get(key, []):
            out.update(_props(doc, sub, depth))
    out.update(schema.get("properties", {}))
    return out


def _fields(doc: dict, schema: dict, prefix: str = "", depth: int = 0) -> set[str]:
    """Dotted field paths of a response body, following objects and arrays of objects (3 levels)."""
    found: set[str] = set()
    for name, sub in _props(doc, schema).items():
        path = f"{prefix}{name}"
        found.add(path)
        if depth >= 3:
            continue
        sub = _resolve(doc, sub)
        branches = [sub, *(_resolve(doc, s) for k in ("anyOf", "oneOf") for s in sub.get(k, []))]
        for b in branches:
            if b.get("type") == "array" and "items" in b:
                found |= _fields(doc, b["items"], f"{path}[].", depth + 1)
            elif "properties" in b or "allOf" in b:
                found |= _fields(doc, b, f"{path}.", depth + 1)
    return found


def _body_schema(op: dict, status: str) -> dict | None:
    content = op.get("responses", {}).get(status, {}).get("content", {})
    return content.get("application/json", {}).get("schema")


def test_operations_match_contract(app) -> None:
    contract = _ops(_contract()["paths"])
    implemented = _ops(app.openapi()["paths"], prefix="/api/v1")
    wrong = {k: v for k, v in implemented.items() if contract.get(k) != v}
    assert wrong == {}, f"operations not in the contract (or with another operationId): {wrong}"
    assert len(implemented) >= 25


def test_response_fields_are_declared_in_contract(app) -> None:
    contract, ours = _contract(), app.openapi()
    undeclared: dict[str, set[str]] = {}
    for path, item in ours["paths"].items():
        for method, op in item.items():
            if method not in METHODS:
                continue
            theirs = contract["paths"][path.removeprefix("/api/v1")][method]
            for status in op.get("responses", {}):
                if not status.startswith("2") or (mine := _body_schema(op, status)) is None:
                    continue
                if not _fields(ours, mine):  # untyped body (file download, redirect)
                    continue
                spec = _body_schema(theirs, status)
                assert spec is not None, f"{method.upper()} {path} {status}: contract has no JSON body"
                extra = _fields(ours, mine) - _fields(contract, spec)
                if extra:
                    undeclared[f"{method.upper()} {path} {status}"] = extra
    assert undeclared == {}, f"response fields missing from openapi-v1.yaml: {undeclared}"
