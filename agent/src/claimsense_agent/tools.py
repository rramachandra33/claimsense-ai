"""One agent's connection to the ClaimSense MCP server.

The MCP server is an HTTP service. Its address is not configured here: the agent looks it up in
the MCP registry (GET /registry/v0/servers) by name. Each agent connects with its own OBO token
in the Authorization header, so it can do only what its token allows (its scopes, its one claim,
five minutes). The same connection is used by the Claude agents through the Agents SDK; in mock
mode the mock agents call the tools directly through this wrapper.

Settings: CLAIMSENSE_MCP_REGISTRY_URL (default http://localhost:8200/registry/v0/servers).
"""
import json
import os
from contextlib import asynccontextmanager

import httpx
import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MCP_SERVER_NAME = "io.claimsense/claims"


class ToolRefused(Exception):
    """A tool call was refused by the API (e.g. 403) or failed."""


class AgentFailed(Exception):
    """An agent could not produce its output (e.g. the model call failed or ran out of turns)."""


class McpNotFound(Exception):
    """The registry did not list the ClaimSense MCP server, or could not be reached."""


def registry_url():
    return os.environ.get("CLAIMSENSE_MCP_REGISTRY_URL", "http://localhost:8200/registry/v0/servers")


def find_mcp_url(name=MCP_SERVER_NAME):
    """Ask the MCP registry where the named server is, and return its streamable-HTTP URL."""
    try:
        response = httpx.get(registry_url(), timeout=10)
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise McpNotFound(f"MCP registry {registry_url()} not reachable: {e}")
    for entry in response.json()["servers"]:
        server = entry["server"]
        if server["name"] != name:
            continue
        for remote in server.get("remotes", []):
            if remote["type"] == "streamable-http":
                return remote["url"]
    raise McpNotFound(f"MCP registry {registry_url()} does not list {name}")


class AgentTools:
    """Calls MCP tools for one agent and remembers what it did."""

    def __init__(self, session, agent):
        self.session = session
        self.agent = agent
        self.calls = []        # (tool name, arguments, "ok" or the refusal)
        self.retrieved = []    # clause ids returned by search_clauses, in order
        self.usage = None      # tokens the agent's model used (set by model-backed agents)

    async def call(self, tool, **arguments):
        result = await self.session.call_tool(tool, arguments)
        text = result.content[0].text if result.content else ""
        if result.is_error:
            self.calls.append((tool, arguments, "error"))
            raise ToolRefused(f"{self.agent}: {tool} failed: {text[:200]}")
        body = json.loads(text)
        if body.get("status", 200) >= 400:
            error = body.get("error", {})
            self.calls.append((tool, arguments, error.get("code", "refused")))
            raise ToolRefused(f"{self.agent}: {tool} refused ({body['status']} {error.get('code')})")
        self.calls.append((tool, arguments, "ok"))
        if tool == "search_clauses":
            for clause in body["clauses"]:
                if clause["clause_id"] not in self.retrieved:
                    self.retrieved.append(clause["clause_id"])
        return body


@asynccontextmanager
async def open_tools(agent, obo_token, run_id):
    """Connect one agent to the MCP server with its OBO token and yield its AgentTools.

    run_id is not sent: the token already carries it, and the API records searches under it."""
    url = find_mcp_url()
    # 30 s to connect or send, 5 minutes to read (the SDK's own defaults for MCP over HTTP).
    timeout = httpx2.Timeout(30, read=300)
    async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + obo_token}, timeout=timeout) as http:
        # The server is stateless, so there is no session to close at the end (terminate_on_close).
        async with streamable_http_client(url, http_client=http, terminate_on_close=False) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield AgentTools(session, agent)
