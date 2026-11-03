# ClaimSense MCP server

The agents' only way to reach claim data. It is deliberately **thin**: each tool makes one call to the
ClaimSense data API (`api/`) with the caller's token and returns the answer unchanged, including
refusals. It has no access rules of its own; the API checks the token, applies the role table and
writes the audit log on every call.

| Tool | Calls |
|---|---|
| `get_claim(claim_id)` | `GET /api/v1/claims/{id}` |
| `get_policy(claim_id)` | `GET /api/v1/claims/{id}/policy` |
| `list_documents(claim_id)` | `GET /api/v1/claims/{id}/documents` |
| `get_document(document_id)` | `GET /api/v1/documents/{id}` |
| `search_clauses(query, top_k)` | `GET /api/v1/clauses` (records the run for citation checks) |

All tools are read-only and work on the run's one claim. There is **no tool for listing claims**
(an agent is given its claim id, and its OBO token is bound to it) and **no write tool**: the claim
note is written by pipeline code after validation, never by an agent.

## How it runs

It is an HTTP service (MCP streamable HTTP, stateless) on port 8200:

| Path | What |
|---|---|
| `POST /mcp` | The five tools. Every request carries the agent's OBO token: `Authorization: Bearer <token>`. A request without one is refused before the API is called. |
| `GET /registry/v0/servers` | The MCP registry (shape of the MCP registry API v0). Agents look up `io.claimsense/claims` here to find the `/mcp` URL; nothing in the agents hard-codes it. |
| `GET /health` | Health check |

The token already names the user, agent, claim and run, so the API records each clause search under
the right run (for the citation checks) without the server passing anything else on.

| Variable | Meaning |
|---|---|
| `CLAIMSENSE_API_URL` | Data API base URL, e.g. `http://localhost:8000` |
| `CLAIMSENSE_MCP_HOST` / `CLAIMSENSE_MCP_PORT` | Where to listen (default `127.0.0.1:8200`; `0.0.0.0` in a container) |
| `CLAIMSENSE_MCP_PUBLIC_URL` | The `/mcp` URL the registry gives agents (default `http://localhost:8200/mcp`) |

Agents read `CLAIMSENSE_MCP_REGISTRY_URL` (default `http://localhost:8200/registry/v0/servers`).

```bash
make mcp                                      # from the repo root (needs `make api`)
make mcp-test                                 # 8 tests (needs `make up`)
```

Built on the MCP Python SDK v2 (`MCPServer`). The folder is called `mcp_server/` so it does not shadow
the `mcp` library.
