"""
UGIE — REST API Module

FastAPI-based HTTP layer for the Universal Growth Engine.
"""

from .app import create_app

__all__ = ["create_app"]
