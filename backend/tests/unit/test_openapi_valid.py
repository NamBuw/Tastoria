"""docs/api/openapi-v1.yaml is a valid OpenAPI 3.1 document (openapi-spec-validator)."""

from __future__ import annotations

import yaml
from conftest import REPO_ROOT
from openapi_spec_validator import validate


def test_contract_is_valid_openapi() -> None:
    validate(yaml.safe_load((REPO_ROOT / "docs/api/openapi-v1.yaml").read_text(encoding="utf-8")))
