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


# Run ids written by a test; the autouse fixture below deletes what they wrote.
RUN_IDS = []


@pytest.fixture(autouse=True)
def clean_up_runs():
    """Remove what the test runs wrote, so the database stays as `make up` left it."""
    yield
    from claimsense_api.db import execute
    for run_id in RUN_IDS:
        execute("""DELETE FROM claimsense.idempotency_keys WHERE note_id IN
                   (SELECT n.note_id FROM claims_mgmt.claim_notes n
                    JOIN claimsense.assessments a USING (assessment_id) WHERE a.run_id = %s)""", (run_id,))
        execute("""DELETE FROM claims_mgmt.claim_notes WHERE assessment_id IN
                   (SELECT assessment_id FROM claimsense.assessments WHERE run_id = %s)""", (run_id,))
        execute("DELETE FROM claimsense.assessments WHERE run_id = %s", (run_id,))
        execute("DELETE FROM claimsense.retrieval_log WHERE run_id = %s", (run_id,))
    RUN_IDS.clear()
