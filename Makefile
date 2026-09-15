.DEFAULT_GOAL := help

.PHONY: help demo demo-notebook demo-docker demo-traefik demo-docker-down setup hooks frontend fmt lint test test-fast test-e2e build cleanroom docs docs-serve check clean

# Print a free host port (stdlib only; no lsof/nc needed).
FREE_PORT := python3 -c 'import socket;s=socket.socket();s.bind(("",0));p=s.getsockname()[1];s.close();print(p)'

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

demo: ## Run the built-in demo app (prints a URL; Ctrl+C to stop)
	uv run python -m indah

demo-notebook: ## Open the demo notebook in JupyterLab (try indah inline in a cell)
	uv run --with jupyterlab jupyter lab examples/demo.ipynb

demo-docker: ## Run the demo in Docker, standalone (prints a localhost URL)
	@PORT=$$($(FREE_PORT)); \
	echo ">>> indah demo: http://localhost:$$PORT/   (Ctrl+C to stop)"; \
	INDAH_HOST_PORT=$$PORT docker compose -f docker-compose.yml up --build

demo-traefik: ## Run the demo in Docker via Traefik (http://indah.localhost/)
	@docker network inspect proxy >/dev/null 2>&1 || { \
		echo "!! Traefik 'proxy' network not found. Start the machine-wide proxy first (docs/DEV-DOCKER.md)."; exit 1; }
	@test -f docker-compose.override.yml || { cp docker-compose.override.yml.example docker-compose.override.yml; \
		echo ">>> created docker-compose.override.yml (gitignored)"; }
	@PORT=$$($(FREE_PORT)); \
	echo ">>> indah demo: http://indah.localhost/   (also http://localhost:$$PORT/ ; Ctrl+C to stop)"; \
	INDAH_HOST_PORT=$$PORT docker compose up --build

demo-docker-down: ## Stop and remove the Docker demo
	docker compose -f docker-compose.yml down 2>/dev/null || true

setup: ## Install dev dependencies into a local venv
	uv sync --extra dev

frontend: ## Rebuild the Svelte shell into the package (needs Node)
	cd frontend && npm ci && npm run build:indah

hooks: ## Install the git pre-push hook
	git config core.hooksPath .githooks
	@echo "pre-push hook installed (bypass once with: git push --no-verify)"

fmt: ## Auto-format the code
	uv run ruff format .
	uv run ruff check --fix .

lint: ## Lint and format-check (no changes)
	uv run ruff check .
	uv run ruff format --check .

test-fast: ## Run the fast layer (unit + integration, no infra)
	uv run pytest -m "unit or integration" -q

test-e2e: ## Run the heavy layer (browser / real launched app)
	uv run pytest -m e2e -q

test: ## Run the full test suite
	uv run pytest -q

build: ## Build the wheel and sdist
	uv build

cleanroom: build ## Prove R4: install the wheel with JS-toolchain tripwires on PATH
	bash scripts/cleanroom.sh

docs: ## Build the documentation site into website/site/
	cd website && uv run --extra docs zensical build --clean

docs-serve: ## Live-preview the documentation site
	cd website && uv run --extra docs zensical serve

check: lint test-fast ## The pre-push gate: lint + fast tests

clean: ## Remove build and cache artifacts
	rm -rf dist build .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
