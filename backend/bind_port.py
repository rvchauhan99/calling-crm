"""HTTP bind port: App Platform sets PORT=8080; local default is 8000."""
import os


def listen_port() -> int:
    raw = os.environ.get("PORT") or "8000"
    try:
        port = int(raw)
    except (TypeError, ValueError):
        return 8000
    if port < 1 or port > 65535:
        return 8000
    return port
