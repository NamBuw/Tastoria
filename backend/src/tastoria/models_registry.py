"""Imports every module's ORM models so `target_metadata` describes all mapped tables (Alembic, schema tests).

Assembly-level helper, like tastoria.app: business modules never import it.
"""

from __future__ import annotations

from tastoria.core.db import Base

target_metadata = Base.metadata
