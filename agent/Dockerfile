# The runner service (the console's Run assessment button) with the four agents. The same image
# runs the MCP server and its registry (command: claimsense-mcp), because the agent installs
# ../mcp_server. Built from the repo root.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/agent/.venv/bin:$PATH"

COPY mcp_server/pyproject.toml /app/mcp_server/pyproject.toml
COPY mcp_server/src /app/mcp_server/src
COPY api/pyproject.toml /app/api/pyproject.toml
WORKDIR /app/agent
COPY agent/pyproject.toml agent/uv.lock agent/README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY agent/src src
RUN uv sync --frozen --no-dev

RUN useradd --create-home app
USER app
EXPOSE 8100
CMD ["uvicorn", "claimsense_agent.runner:app", "--host", "0.0.0.0", "--port", "8100"]
