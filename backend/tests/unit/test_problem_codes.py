from __future__ import annotations

import yaml
from conftest import REPO_ROOT

from tastoria.core.errors import BACKEND_ONLY_CODES, ProblemCode


def test_problem_codes_match_openapi_contract() -> None:
    spec = yaml.safe_load((REPO_ROOT / "docs/api/openapi-v1.yaml").read_text(encoding="utf-8"))
    contract = spec["components"]["schemas"]["ProblemCode"]["enum"]
    ours = [c.value for c in ProblemCode if c not in BACKEND_ONLY_CODES]
    assert ours == contract
