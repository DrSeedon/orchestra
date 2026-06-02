"""Shared dependencies for routers — avoids importing from main."""

from app.manager import SessionManager

manager = SessionManager()
