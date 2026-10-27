"""Start the data API on a free local port for the pipeline tests.

The MCP server runs as a separate process and calls the API over HTTP, so the API has to really
listen on a port; an in-process test client is not enough. Tests that need it skip cleanly when
the database is not running (`make up`).
"""
import os
import socket
import threading
import time

os.environ.setdefault("CLAIMSENSE_JWT_SECRET", "test-secret-for-pytest-only-0123456789abcdef")

import psycopg  # noqa: E402
import pytest  # noqa: E402
import uvicorn  # noqa: E402

from claimsense_api.db import db_url  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_api():
    """The API's base URL. Also set as CLAIMSENSE_API_URL for the pipeline and the MCP server."""
    try:
        psycopg.connect(db_url()).close()
    except psycopg.OperationalError:
        pytest.skip("database not running (run `make up`)")

    from claimsense_api.main import app
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):                 # wait up to 5 s for it to start
        if server.started:
            break
        time.sleep(0.05)

    url = f"http://127.0.0.1:{port}"
    os.environ["CLAIMSENSE_API_URL"] = url
    yield url
    server.should_exit = True
    thread.join(timeout=5)
