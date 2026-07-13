"""Entry point that binds the host/port from WEB_BIND in .env, so the serving
address has a single source of truth (the .env file) instead of being hardcoded
on the uvicorn command line. Importing app.main runs its .env loader first, so
WEB_BIND is populated by the time we read it here.

Run with: python run.py  (or .venv/bin/python run.py)
"""
import os

import uvicorn

from app.main import app


def _parse_bind(value: str) -> tuple[str, int]:
    """Split a `host:port` string; fall back to 127.0.0.1:8081 for a missing or
    malformed value rather than crashing on startup."""
    host, sep, port = value.rpartition(":")
    if not sep or not port.isdigit():
        return "127.0.0.1", 8081
    return (host or "127.0.0.1"), int(port)


if __name__ == "__main__":
    host, port = _parse_bind(os.environ.get("WEB_BIND", "127.0.0.1:8081"))
    # Behind nginx: trust its X-Forwarded-* headers (default to localhost, the
    # same host the reverse proxy runs on; override via WEB_FORWARDED_ALLOW_IPS).
    uvicorn.run(
        app,
        host=host,
        port=port,
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("WEB_FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )
