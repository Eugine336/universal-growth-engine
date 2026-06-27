"""
UGIE REST API entry point.

Run with: uvicorn api.rest.main:app --host 0.0.0.0 --port 8000
"""

from .app import create_app

app = create_app()
