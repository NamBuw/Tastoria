"""Every implemented operation is in docs/api/openapi-v1.yaml with the same method, path and operationId."""

from __future__ import annotations

import yaml
from conftest import REPO_ROOT

METHODS = {"get", "post", "put", "patch", "delete"}


def _ops(paths: dict, prefix: str = "") -> dict[tuple[str, str], str]:
    return {
        (method.upper(), path.removeprefix(prefix)): op["operationId"]
        for path, item in paths.items()
        for method, op in item.items()
        if method in METHODS
    }


def test_operations_match_contract(app) -> None:
    contract = _ops(yaml.safe_load((REPO_ROOT / "docs/api/openapi-v1.yaml").read_text(encoding="utf-8"))["paths"])
    implemented = _ops(app.openapi()["paths"], prefix="/api/v1")
    wrong = {k: v for k, v in implemented.items() if contract.get(k) != v}
    assert wrong == {}, f"operations not in the contract (or with another operationId): {wrong}"
    assert len(implemented) == 25
