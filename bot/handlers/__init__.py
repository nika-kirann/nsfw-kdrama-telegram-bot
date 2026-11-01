from telegram.ext import Application
from . import admin, viewer


def register(app: Application) -> None:
    for h in [*admin.handlers(), *viewer.handlers()]:
        app.add_handler(h)
