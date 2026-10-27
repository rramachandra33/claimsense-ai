# ClaimSense MCP server

The agents' only way to reach claim data. It is deliberately **thin**: each tool makes one call to the
ClaimSense data API (`api/`) with the caller's token and returns the answer unchanged, including
refusals. It has no access rules of its own; the API checks the token, applies the role table and
writes the audit log on every call.

| Tool | Calls |
|---|---|
| `list_claims` | `GET /api/v1/claims` |
| `get_claim(claim_id)` | `GET /api/v1/claims/{id}` |
| `get_policy(claim_id)` | `GET /api/v1/claims/{id}/policy` |
| `list_documents(claim_id)` | `GET /api/v1/claims/{id}/documents` |
| `get_document(document_id)` | `GET /api/v1/documents/{id}` |
| `search_clauses(query, top_k)` | `GET /api/v1/clauses` (records the run for citation checks) |

All tools are read-only. There is **no write tool**: the claim note is written by pipeline code after
validation, never by an agent.

## How it is started

The pipeline starts it for one run over **stdio**, with:

| Variable | Meaning |
|---|---|
| `CLAIMSENSE_API_URL` | Data API base URL, e.g. `http://localhost:8000` |
| `CLAIMSENSE_TOKEN` | The token to act with (later: the agent's short-lived OBO token) |
| `CLAIMSENSE_RUN_ID` | The pipeline run id, so searches are recorded in `retrieval_log` |
| `CLAIMSENSE_AGENT` | The agent's name, recorded with each search |

```bash
cd mcp_server && uv run claimsense-mcp        # normally started by the pipeline, not by hand
make mcp-test                                 # from the repo root (needs `make up`)
```

Built on the MCP Python SDK v2 (`MCPServer`). The folder is called `mcp_server/` so it does not shadow
the `mcp` library.
