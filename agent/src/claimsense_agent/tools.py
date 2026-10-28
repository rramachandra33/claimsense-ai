"""One agent's connection to the ClaimSense MCP server.

For each agent the pipeline starts the MCP server over stdio with that agent's OBO token, so the
agent can do only what its token allows (its scopes, its one claim, five minutes). The same
server is what a real model will use through the Agents SDK; in mock mode the mock agents call
the tools directly through this wrapper.
"""
import json
import os
import sys
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .api import api_url


class ToolRefused(Exception):
    """A tool call was refused by the API (e.g. 403) or failed."""


class AgentFailed(Exception):
    """An agent could not produce its output (e.g. the model call failed or ran out of turns)."""


def mcp_server_params(agent, obo_token, run_id):
    """How to start the MCP server for one agent."""
    env = dict(os.environ)
    env.update({
        "CLAIMSENSE_API_URL": api_url(),
        "CLAIMSENSE_TOKEN": obo_token,
        "CLAIMSENSE_RUN_ID": run_id,
        "CLAIMSENSE_AGENT": agent,
    })
    return StdioServerParameters(command=sys.executable, args=["-m", "claimsense_mcp.server"], env=env)


class AgentTools:
    """Calls MCP tools for one agent and remembers what it did."""

    def __init__(self, session, agent):
        self.session = session
        self.agent = agent
        self.calls = []        # (tool name, arguments, "ok" or the refusal)
        self.retrieved = []    # clause ids returned by search_clauses, in order

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
    """Start the MCP server for one agent and yield its AgentTools."""
    params = mcp_server_params(agent, obo_token, run_id)
    # The server logs each HTTP call to stderr; keep that out of the pipeline's output.
    with open(os.devnull, "w") as quiet:
        errlog = sys.stderr if os.environ.get("CLAIMSENSE_MCP_DEBUG") else quiet
        async with stdio_client(params, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield AgentTools(session, agent)
