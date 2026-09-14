.DEFAULT_GOAL := help

.PHONY: help demo setup hooks frontend fmt lint test test-fast test-e2e build check clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

demo: ## Run the built-in demo app (prints a URL; Ctrl+C to stop)
	uv run python -m indah

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

check: lint test-fast ## The pre-push gate: lint + fast tests

clean: ## Remove build and cache artifacts
	rm -rf dist build .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
