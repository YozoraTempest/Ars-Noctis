import os


MODE = os.environ.get("APP_MODE", "production")


def current_mode() -> str:
    return MODE
