"""Start the data API and the MCP server on free local ports, in this process (for the tests and
the evaluation run).

The agents reach the MCP server over HTTP, and the MCP server calls the API over HTTP, so both
have to really listen on a port. Needs the claimsense-api package (`uv run --extra dev`) and the
database (`make up`).
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


def serve_in_thread(app, port):
    """Run an ASGI app with uvicorn in a background thread; return the uvicorn server once it listens."""
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):                 # wait up to 5 s for it to start
        if server.started:
            break
        time.sleep(0.05)
    return server, thread


class LocalApi:
    """The API and the MCP server (with its registry), each in a background thread.
    Use start() and stop(), or a `with` block; start() returns the API's URL."""

    def __init__(self):
        # Tokens are minted and checked in this process, so any secret will do.
        os.environ.setdefault("CLAIMSENSE_JWT_SECRET", secrets.token_hex(32))
        self.running = []                    # (uvicorn server, thread) pairs
        self.url = None

    def start(self):
        from claimsense_api.main import app as api_app
        from claimsense_mcp.server import http_app

        api_port = free_port()
        self.running.append(serve_in_thread(api_app, api_port))
        self.url = f"http://127.0.0.1:{api_port}"
        os.environ["CLAIMSENSE_API_URL"] = self.url     # for the pipeline and the MCP server

        mcp_port = free_port()
        mcp_url = f"http://127.0.0.1:{mcp_port}"
        os.environ["CLAIMSENSE_MCP_PUBLIC_URL"] = mcp_url + "/mcp"                      # what the registry lists
        os.environ["CLAIMSENSE_MCP_REGISTRY_URL"] = mcp_url + "/registry/v0/servers"   # where agents look
        self.running.append(serve_in_thread(http_app("127.0.0.1"), mcp_port))
        return self.url

    def stop(self):
        for server, thread in self.running:
            server.should_exit = True
            thread.join(timeout=5)
        self.running = []

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
