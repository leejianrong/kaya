"""Declarative models.

Empty of tables on purpose: the ``user`` mirror and the ``note`` table land in KAN-533. The
``Base`` and this module both exist now because ``alembic/env.py`` imports this package to build
``target_metadata`` — an autogenerate run against metadata that never imported the models emits a
migration that *drops* every table it doesn't know about.

When a model is added, import it here so it reaches ``Base.metadata``.
"""

from app.models.base import Base

__all__ = ["Base"]
