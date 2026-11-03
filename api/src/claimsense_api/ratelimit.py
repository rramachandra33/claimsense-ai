"""Rate limit: at most N API requests per user per minute.

The count is kept in PostgreSQL, not in memory, because on AWS Lambda many copies of the API run
at once and each would otherwise keep its own count. An agent's calls count for the user it acts
for (one assessment run is about 25 calls), so N must leave room for a few runs a minute.

CLAIMSENSE_RATE_LIMIT_PER_MINUTE sets N. Unset or 0 means no limit (local development, tests and
the evaluation run); the deployed API sets it.
"""
import os

from .db import connect


def limit_per_minute():
    return int(os.environ.get("CLAIMSENSE_RATE_LIMIT_PER_MINUTE", "0") or "0")


def allow_request(user_id):
    """Count this request for the user in the current minute. False if it is over the limit."""
    limit = limit_per_minute()
    if limit <= 0:
        return True
    with connect() as conn:
        row = conn.execute(
            """INSERT INTO claimsense.rate_limit (user_id, window_start, request_count)
               VALUES (%s, date_trunc('minute', now()), 1)
               ON CONFLICT (user_id, window_start)
               DO UPDATE SET request_count = claimsense.rate_limit.request_count + 1
               RETURNING request_count""",
            (user_id,),
        ).fetchone()
        # Old minutes are no longer needed; keep the table small.
        conn.execute("""DELETE FROM claimsense.rate_limit
                        WHERE user_id = %s AND window_start < now() - interval '1 hour'""", (user_id,))
    return row["request_count"] <= limit
