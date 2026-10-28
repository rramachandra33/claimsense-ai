"""The pipeline's own calls to the data API, made with the adjuster's token.

Pipeline code (not an agent) uses this to read what the code facts need, to ask for each agent's
OBO token, and to write the one note at the end. Agents never get this client: they reach data
only through the MCP server, with their own OBO token.
"""
import os
import random
import time

import httpx

# Retries for the note write (open question 3 follow-up: timeouts are retried with exponential
# backoff and jitter; the Idempotency-Key makes a retry return the stored note, not a second one).
WRITE_ATTEMPTS = 4
BACKOFF_SECONDS = 0.5


def api_url():
    return os.environ.get("CLAIMSENSE_API_URL", "http://localhost:8000")


class ApiError(Exception):
    """The API refused or failed. code is the API's error code, e.g. forbidden."""

    def __init__(self, status, code, message):
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message


def raise_for_error(response):
    if response.status_code < 400:
        return
    try:
        error = response.json()["error"]
        raise ApiError(response.status_code, error["code"], error["message"])
    except (ValueError, KeyError):
        raise ApiError(response.status_code, "http_error", response.text[:200])


def dev_login(user_id, base_url=None):
    """A development token for a user (the API must run with CLAIMSENSE_DEV_LOGIN=1)."""
    response = httpx.post((base_url or api_url()) + "/api/v1/dev/login",
                          json={"user_id": user_id}, timeout=10)
    raise_for_error(response)
    return response.json()["token"]


class ApiClient:
    def __init__(self, token, base_url=None, timeout=30):
        self.base_url = base_url or api_url()
        self.token = token
        self.timeout = timeout

    def headers(self, extra=None):
        headers = {"Authorization": "Bearer " + self.token}
        if extra:
            headers.update(extra)
        return headers

    def get(self, path, params=None):
        response = httpx.get(self.base_url + path, params=params, headers=self.headers(),
                             timeout=self.timeout)
        raise_for_error(response)
        return response.json()

    def post(self, path, body, extra_headers=None):
        response = httpx.post(self.base_url + path, json=body, headers=self.headers(extra_headers),
                              timeout=self.timeout)
        raise_for_error(response)
        return response.json()

    def me(self):
        return self.get("/api/v1/me")

    def claim_file(self, claim_id):
        """What the code facts need: the claim, its policy and its document list."""
        claim = self.get(f"/api/v1/claims/{claim_id}")["claim"]
        policy = self.get(f"/api/v1/claims/{claim_id}/policy")["policy"]
        documents = self.get(f"/api/v1/claims/{claim_id}/documents")["documents"]
        return claim, policy, documents

    def clause_exists(self, clause_id):
        """True if the clause is in the loaded policy manual (a quarantined clause counts as absent)."""
        try:
            self.get(f"/api/v1/clauses/{clause_id}")
            return True
        except ApiError as e:
            if e.status == 404:
                return False
            raise

    def retrieve_clause(self, clause_id, run_id):
        """Look a clause up within a run, so it counts as retrieved there. False if it does not exist."""
        try:
            self.get(f"/api/v1/clauses/{clause_id}", params={"run_id": run_id, "agent": "code"})
            return True
        except ApiError as e:
            if e.status == 404:
                return False
            raise

    def obo_token(self, claim_id, agent, run_id):
        body = {"claim_id": claim_id, "agent": agent, "run_id": run_id}
        return self.post("/api/v1/obo/token", body)["token"]

    def write_note(self, claim_id, note, idempotency_key, sleep=time.sleep):
        """Write the note, retrying timeouts and server errors with backoff and jitter.

        Refusals (4xx) are not retried: sending the same body again would get the same answer.
        """
        path = f"/api/v1/claims/{claim_id}/notes"
        headers = {"Idempotency-Key": idempotency_key}
        for attempt in range(1, WRITE_ATTEMPTS + 1):
            try:
                return self.post(path, note, extra_headers=headers)
            except httpx.TransportError:            # timeout, connection refused or dropped
                if attempt == WRITE_ATTEMPTS:
                    raise
            except ApiError as e:
                if e.status < 500 or attempt == WRITE_ATTEMPTS:
                    raise
            # 0.5 s, 1 s, 2 s ... plus up to that much again at random, so retries spread out
            delay = BACKOFF_SECONDS * (2 ** (attempt - 1))
            sleep(delay + random.uniform(0, delay))
