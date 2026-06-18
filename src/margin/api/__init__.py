"""Public entry point for the Margin FastAPI application.

This module exposes the default application instance and the factory function
used to create configurable instances for production, testing, and development.
"""

from margin.api.main import app, create_app

__all__ = ["app", "create_app"]
