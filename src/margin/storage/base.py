"""Shared SQLAlchemy declarative base for ORM models.

This module defines the declarative base class that all PostgreSQL ORM models in the
project must inherit from.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all PostgreSQL ORM models.."""
