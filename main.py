"""Entrada na raiz para a Vercel detetar o FastAPI (`app`) sem pyproject/uv."""

from app.main import app

__all__ = ["app"]
