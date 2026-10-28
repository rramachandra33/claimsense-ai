# The ClaimSense Engagement — one entry point for everything.
# Every target is idempotent and safe to re-run. `make help` lists them.
.DEFAULT_GOAL := help
SHELL := /bin/bash

PORT       ?= 3100
DB_URL     ?= postgresql://claimsense:claimsense@localhost:5433/claimsense
BASE_URL   ?= http://localhost:$(PORT)/api/v1
CONSOLE    ?= http://localhost:$(PORT)
CLAIM      ?= CLM-2024-1800
AS         ?= alice
BRAIN      ?= mock
AWS_PROFILE ?= claimsense

export CLAIMSENSE_DB_URL      := $(DB_URL)
export CLAIMSENSE_BASE_URL    := $(BASE_URL)
export CLAIMSENSE_CONSOLE_URL := $(CONSOLE)

.PHONY: help up deps seed api api-test mcp-test token web web-dev agent runner eval test down clean doctor

help: ## show this list
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

up: ## Postgres + schema + course-fixture seed (one command)
	cd platform/db && docker compose up -d
	@echo "==> waiting for Postgres…"
	@until (cd platform/db && docker compose exec -T claimsense-db pg_isready -U claimsense >/dev/null 2>&1); do sleep 1; done
	$(MAKE) seed
	@echo ""
	@echo "==> ready. next: make web   (console on $(CONSOLE))"

deps: ## install the console's node deps
	@# check a real dependency, not just the folder: a half-installed node_modules
	@# silently 500s every API route, which is a miserable thing to debug in class.
	@cd platform/web && { node -e "require.resolve('next')" >/dev/null 2>&1 || npm install --silent; }
	@cd platform/web && node -e "require.resolve('next')" >/dev/null 2>&1 || \
	  { echo "!! node deps still missing — run: cd platform/web && npm install"; exit 1; }
	@cd platform/web && printf 'CLAIMSENSE_API_URL=http://localhost:8000\nCLAIMSENSE_RUNNER_URL=http://localhost:8100\n' > .env.local

seed: ## rebuild the seed CSVs from data/course_fixtures and reload the database
	cd platform/db && ./load.sh

api: ## run the ClaimSense data API on :8000 (needs CLAIMSENSE_JWT_SECRET; see api/.env.example)
	cd api && uv run uvicorn claimsense_api.main:app --app-dir src --port 8000

api-test: ## the data API's access tests (needs `make up` first)
	cd api && uv run --extra dev pytest -q

mcp-test: ## the MCP server's tool tests (needs `make up` first)
	cd mcp_server && uv run --extra dev pytest -q

token: ## print a dev token: make token USER=alice
	cd api && uv run python scripts/mint_dev_token.py $(USER)

web: deps ## build + serve the Ops Console on :$(PORT)
	cd platform/web && npm run build && PORT=$(PORT) npm run start

web-dev: deps ## hot-reload the console instead (development)
	cd platform/web && PORT=$(PORT) npm run dev

agent: ## assess a claim: make agent CLAIM=CLM-2024-1800 AS=alice [BRAIN=bedrock] (needs make api)
	cd agent && AWS_PROFILE=$(AWS_PROFILE) uv run claimsense-agent run --claim $(CLAIM) --user $(AS) --brain $(BRAIN)

runner: ## the service behind the console's Run assessment button (port 8100) [BRAIN=bedrock]
	cd agent && AWS_PROFILE=$(AWS_PROFILE) CLAIMSENSE_BRAIN=$(BRAIN) uv run uvicorn claimsense_agent.runner:app --port 8100

eval: ## the 60-case evaluation (needs make up): make eval [BRAIN=bedrock] — mock is the CI gate
	cd agent && AWS_PROFILE=$(AWS_PROFILE) uv run --extra dev claimsense-agent eval --brain $(BRAIN) --min-pass 0.9

golden: ## the release gate: the 60 cases on Claude (about $3.50 and 30 minutes)
	$(MAKE) --no-print-directory eval BRAIN=bedrock

verify: ## $$0 smoke gate: prerequisites + smoke eval + unit tests. Run this first.
	@$(MAKE) --no-print-directory doctor
	@echo
	@$(MAKE) --no-print-directory eval
	@echo
	@$(MAKE) --no-print-directory test
	@echo "verify: OK"

test: ## the agent pipeline's tests (needs make up; starts its own API)
	cd agent && uv run --extra dev pytest -q

doctor: ## check prerequisites and report what's missing
	@echo "docker : $$(docker --version 2>/dev/null || echo MISSING)"
	@echo "node   : $$(node -v 2>/dev/null || echo MISSING)"
	@echo "python : $$(python3 -V 2>/dev/null || echo MISSING)"
	@echo "uv     : $$(uv --version 2>/dev/null || echo 'MISSING — https://docs.astral.sh/uv/')"
	@echo "aws    : $$(aws --version 2>/dev/null || echo 'missing (only needed for the cloud rungs)')"
	@echo "db     : $$(cd platform/db && docker compose exec -T claimsense-db pg_isready -U claimsense 2>/dev/null || echo 'not running — make up')"

down: ## stop Postgres (data survives)
	cd platform/db && docker compose down

clean: ## stop Postgres AND delete the data volume
	cd platform/db && docker compose down -v
