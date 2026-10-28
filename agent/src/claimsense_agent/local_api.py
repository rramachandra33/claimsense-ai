"""Start the data API on a free local port, in this process (for the tests and the evaluation run).

The MCP server runs as a separate process and calls the API over HTTP, so the API has to really
listen on a port. Needs the claimsense-api package (`uv run --extra dev`) and the database (`make up`).
"""
import os
import secrets
import socket
import threading
import time


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def database_is_up():
    import psycopg
    from claimsense_api.db import db_url
    try:
        psycopg.connect(db_url()).close()
        return True
    except psycopg.OperationalError:
        return False


class LocalApi:
    """The API running in a background thread. Use start() and stop(), or a `with` block."""

    def __init__(self):
        # Tokens are minted and checked in this process, so any secret will do.
        os.environ.setdefault("CLAIMSENSE_JWT_SECRET", secrets.token_hex(32))
        self.server = None
        self.thread = None
        self.url = None

    def start(self):
        import uvicorn
        from claimsense_api.main import app

        port = free_port()
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(100):                 # wait up to 5 s for it to start
            if self.server.started:
                break
            time.sleep(0.05)
        self.url = f"http://127.0.0.1:{port}"
        os.environ["CLAIMSENSE_API_URL"] = self.url     # for the pipeline and the MCP server
        return self.url

    def stop(self):
        if self.server:
            self.server.should_exit = True
            self.thread.join(timeout=5)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
