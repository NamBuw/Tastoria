"""Imports every module's ORM models so `target_metadata` describes all mapped tables (Alembic, schema tests).

Assembly-level helper, like tastoria.app: business modules never import it.
"""

from __future__ import annotations

import tastoria.core.models  # noqa: F401
import tastoria.modules.catalog.models  # noqa: F401
import tastoria.modules.cooking.models  # noqa: F401
import tastoria.modules.events.models  # noqa: F401
import tastoria.modules.identity.models  # noqa: F401
import tastoria.modules.meal.models  # noqa: F401
import tastoria.modules.mlops.models  # noqa: F401
import tastoria.modules.pantry.models  # noqa: F401
import tastoria.modules.privacy.models  # noqa: F401
import tastoria.modules.profile.models  # noqa: F401
import tastoria.modules.scan.models  # noqa: F401
import tastoria.modules.substitute.models  # noqa: F401
import tastoria.modules.survey.models  # noqa: F401
from tastoria.core.db import Base

target_metadata = Base.metadata
