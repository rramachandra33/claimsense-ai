"""Start the data API on a free local port for the pipeline tests.

The MCP server runs as a separate process and calls the API over HTTP, so the API has to really
listen on a port; an in-process test client is not enough. Tests that need it skip cleanly when
the database is not running (`make up`).
"""
import os

os.environ.setdefault("CLAIMSENSE_JWT_SECRET", "test-secret-for-pytest-only-0123456789abcdef")

import pytest  # noqa: E402

from claimsense_agent.local_api import LocalApi, database_is_up  # noqa: E402


@pytest.fixture(scope="session")
def live_api():
    """The API's base URL. Also set as CLAIMSENSE_API_URL for the pipeline and the MCP server."""
    if not database_is_up():
        pytest.skip("database not running (run `make up`)")
    with LocalApi() as url:
        yield url


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
