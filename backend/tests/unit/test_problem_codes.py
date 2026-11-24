from __future__ import annotations

import yaml
from conftest import REPO_ROOT

from tastoria.core.errors import BACKEND_ONLY_CODES, ProblemCode, problem_body


def test_problem_codes_match_openapi_contract() -> None:
    spec = yaml.safe_load((REPO_ROOT / "docs/api/openapi-v1.yaml").read_text(encoding="utf-8"))
    contract = spec["components"]["schemas"]["ProblemCode"]["enum"]
    ours = [c.value for c in ProblemCode if c not in BACKEND_ONLY_CODES]
    assert ours == contract


def test_problem_body_does_not_overwrite_core_fields() -> None:
    body = problem_body(
        409,
        ProblemCode.scan_not_editable,
        detail="Không sửa được",
        instance="/api/v1/scans/1/items",
        extra={
            "status": "discarded",
            "code": "hijacked",
            "type": "https://evil.example/problem",
            "title": "Hijacked",
            "detail": "Hijacked detail",
            "instance": "/hijacked",
            "scan_status": "discarded",
        },
    )
    assert body["status"] == 409
    assert body["code"] == "scan_not_editable"
    assert body["type"] == "https://tastoria.ctslab.net/problems/scan_not_editable"
    assert body["title"] != "Hijacked"
    assert body["detail"] == "Không sửa được"
    assert body["instance"] == "/api/v1/scans/1/items"
    assert body["scan_status"] == "discarded"
