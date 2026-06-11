"""Shared dependencies for routers — avoids importing from main."""

from fastapi.templating import Jinja2Templates

from app.manager import SessionManager

manager = SessionManager()
templates = Jinja2Templates(directory="app/templates")
