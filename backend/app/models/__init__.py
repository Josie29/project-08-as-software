"""ORM models.

Each model module must be imported here so that `Base.metadata` is fully populated
before Alembic autogenerate runs — a model that is never imported is silently absent
from generated migrations.
"""

from app.db import Base

__all__ = ["Base"]
