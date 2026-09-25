MOCKER ?= mocker
APPLE_CONTAINER_BIN ?= /opt/homebrew/bin/container
COMPOSE_FILE ?= compose.yml
API_PORT ?= 8010
WEB_PORT ?= 3010
CODEX_HARNESS_PORT ?= 8765
API_BASE ?= http://127.0.0.1:$(API_PORT)
WEB_BASE ?= http://127.0.0.1:$(WEB_PORT)
SERVICE ?= api

.PHONY: help check migrate stripe_login setup_stripe setup_stripe_test setup_stripe_live runtime-start test browser-test acceptance-evidence spec-audit persistence-check container-config container-build container-up container-health harness-health harness-check container-ps container-logs container-shell container-down

help: ## Show the Apple Container + Mocker commands.
	@awk 'BEGIN {FS = ":.*##"; printf "\nMemory Spark — Apple Container + Mocker\n\nUsage: make <target>\n\n"} /^[a-zA-Z0-9][a-zA-Z0-9_.-]*:.*##/ {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

check: ## Verify Mocker and Apple Container are installed.
	@command -v $(MOCKER) >/dev/null || { echo "Missing Mocker. Install with: brew tap us/tap && brew install mocker"; exit 1; }
	@test -x "$(APPLE_CONTAINER_BIN)" || { echo "Missing Apple Container CLI: $(APPLE_CONTAINER_BIN)"; exit 1; }
	@echo "Mocker: $$($(MOCKER) --version)"
	@echo "Apple Container: $$($(APPLE_CONTAINER_BIN) --version)"

migrate: ## Apply the Supabase story-entitlement migration.
	@set -a; \
	if test -f .env; then . ./.env; fi; \
	set +a; \
	test -n "$${SUPABASE_DB_URL:-}" || { echo "Set SUPABASE_DB_URL in .env."; exit 2; }; \
	command -v psql >/dev/null || { echo "Missing psql. Install the PostgreSQL client first."; exit 1; }; \
	psql "$${SUPABASE_DB_URL}" -v ON_ERROR_STOP=1 -f supabase/migrations/202609250003_story_entitlements.sql

STRIPE_MODE ?= test
MEMORY_SPARK_PUBLIC_URL ?=
STRIPE_WEBHOOK_PATH ?= /api/v1/memoir/story/stripe/webhook
STRIPE_WEBHOOK_URL ?= $(if $(MEMORY_SPARK_PUBLIC_URL),$(patsubst %/,%,$(MEMORY_SPARK_PUBLIC_URL))$(STRIPE_WEBHOOK_PATH),)
STRIPE_SETUP_ARGS ?=
export STRIPE_SECRET_KEY

setup_stripe: ## Create or reuse the one-time Stripe catalog; use STRIPE_MODE=live for production.
	@set -e; \
	if test -z "$${STRIPE_SECRET_KEY:-}" && test -f .env; then set -a; . ./.env; set +a; fi; \
	if test -n "$(STRIPE_WEBHOOK_URL)"; then \
		python3 infra/stripe/setup_stripe.py --mode "$(STRIPE_MODE)" --webhook-url "$(STRIPE_WEBHOOK_URL)" --yes $(STRIPE_SETUP_ARGS); \
	else \
		python3 infra/stripe/setup_stripe.py --mode "$(STRIPE_MODE)" --yes $(STRIPE_SETUP_ARGS); \
	fi

stripe_login: ## Authenticate the Stripe CLI for local webhook forwarding.
	@command -v stripe >/dev/null || { echo "Missing Stripe CLI. Install it from https://docs.stripe.com/stripe-cli."; exit 1; }
	@stripe login

setup_stripe_test: ## Create or reuse the test-mode catalog with STRIPE_SECRET_KEY=sk_test_....
	@test -n "$${STRIPE_SECRET_KEY:-}" || { echo "Pass STRIPE_SECRET_KEY=sk_test_... to this target."; exit 2; }
	@case "$${STRIPE_SECRET_KEY}" in sk_test_*) ;; *) echo "setup_stripe_test requires a key beginning with sk_test_."; exit 2 ;; esac
	@if test -n "$(STRIPE_WEBHOOK_URL)"; then \
		python3 infra/stripe/setup_stripe.py --mode test --auth api-key --webhook-url "$(STRIPE_WEBHOOK_URL)" --yes $(STRIPE_SETUP_ARGS); \
	else \
		python3 infra/stripe/setup_stripe.py --mode test --auth api-key --yes $(STRIPE_SETUP_ARGS); \
	fi

setup_stripe_live: ## Create or reuse the live catalog with STRIPE_SECRET_KEY=sk_live_....
	@test -n "$${STRIPE_SECRET_KEY:-}" || { echo "Pass STRIPE_SECRET_KEY=sk_live_... to this target."; exit 2; }
	@case "$${STRIPE_SECRET_KEY}" in sk_live_*) ;; *) echo "setup_stripe_live requires a key beginning with sk_live_."; exit 2 ;; esac
	@test -n "$(STRIPE_WEBHOOK_URL)" || { echo "Set MEMORY_SPARK_PUBLIC_URL=https://<public-domain> (or STRIPE_WEBHOOK_URL=https://<api-domain>/api/v1/memoir/story/stripe/webhook) for live setup."; exit 2; }
	@python3 infra/stripe/setup_stripe.py --mode live --auth api-key --webhook-url "$(STRIPE_WEBHOOK_URL)" --yes $(STRIPE_SETUP_ARGS)

runtime-start: check ## Start the Apple Container runtime.
	@$(APPLE_CONTAINER_BIN) system start

test: ## Run the local Python test suite.
	@python3 -m pytest -q

browser-test: ## Run the complete first-chapter Playwright journey against a local server.
	@python3 /Users/bohuihan/.codex/skills/webapp-testing/scripts/with_server.py \
		--server "MEMORY_SPARK_TEST_MODE=1 python3 -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000" \
		--port 8000 -- python3 tests/browser_e2e.py --base-url http://127.0.0.1:8000

acceptance-evidence: ## Run AT-001 through AT-055 and write the evidence report.
	@python3 scripts/run_acceptance_evidence.py

spec-audit: ## Verify every normative section 19.2 route is represented.
	@python3 scripts/audit_spec_routes.py

persistence-check: ## Verify the local store survives an application restart.
	@python3 -m pytest -q tests/test_persistence.py

container-config: check ## Validate the Compose model through Mocker.
	@$(MOCKER) compose config -f $(COMPOSE_FILE) --quiet
	@echo "Compose configuration: valid"

container-build: runtime-start ## Build the local images without changing running services.
	@MEMORY_SPARK_CODEX_VERSION=$${MEMORY_SPARK_CODEX_VERSION:-0.156.1} $(MOCKER) compose build -f $(COMPOSE_FILE)

container-up: runtime-start ## Build and start the complete local stack.
	@mkdir -p var/codex-home var/memory-spark
	@$(MOCKER) compose build -f $(COMPOSE_FILE)
	@set -e; \
	$(MOCKER) compose down -f $(COMPOSE_FILE) --remove-orphans >/dev/null 2>&1 || true; \
	$(MOCKER) rm -f memory-spark-api-1 memory-spark-worker-1 memory-spark-web-1 memory-spark-codex-worker-1 memory-spark-codex-harness-1 >/dev/null 2>&1 || true; \
	$(MOCKER) compose up -f $(COMPOSE_FILE) --no-deps --detach api worker web codex-worker codex-harness; \
	$(MOCKER) compose up -f $(COMPOSE_FILE) --no-recreate --no-deps --detach --wait --wait-timeout 120 api worker web codex-worker codex-harness
	@$(MAKE) --no-print-directory container-health

container-health: check ## Verify API, web shell, web-to-API proxy, and Codex harness.
	@python3 scripts/verify_container_stack.py --api-base $(API_BASE) --web-base $(WEB_BASE) --harness-port $(CODEX_HARNESS_PORT) --expected-storage supabase-user-memory+filesystem-objects
	@$(MAKE) --no-print-directory harness-health

harness-health: check ## Verify the Codex exec-server protocol inside its container.
	@$(MOCKER) compose exec -f $(COMPOSE_FILE) -T codex-harness node /workspace/scripts/verify_codex_harness.mjs ws://127.0.0.1:8765

harness-check: container-up ## Run the repository and specification checks inside the Codex harness container.
	@$(MOCKER) compose exec -f $(COMPOSE_FILE) -T codex-harness node /workspace/scripts/verify_codex_harness.mjs ws://127.0.0.1:8765 "python3 scripts/run_acceptance_evidence.py && python3 -m pytest -q && python3 scripts/audit_spec_routes.py --spec docs/Memory_Spark_Full_Specification_v1.0.md"

container-ps: check ## Show the running services.
	@$(MOCKER) ps --format '{{.Names}} {{.Status}}' | awk '$$1 ~ /^memory-spark-/'
	@$(MOCKER) compose ps -f $(COMPOSE_FILE)

container-logs: check ## Follow logs for SERVICE=api, web, or codex-harness.
	@$(MOCKER) compose logs -f $(COMPOSE_FILE) --tail 200 $(SERVICE)

container-shell: check ## Open a shell in SERVICE=api.
	@$(MOCKER) compose exec -f $(COMPOSE_FILE) -it $(SERVICE) sh

# harness-provider-check: container-up ## Verify the harness is configured for the local llm_provider.
# 	@$(MOCKER) compose exec -f $(COMPOSE_FILE) -T codex-harness sh -lc 'grep -q "model_provider = \"llm_provider\"" "$$CODEX_HOME/config.toml" && grep -q "requires_openai_auth = false" "$$CODEX_HOME/config.toml"'
# 	@echo "Codex harness: local llm_provider configured; codex login is not required"

# harness-run: container-up ## Run Codex against the local llm_provider; pass PROMPT='...'.
# 	@test -n "$(PROMPT)" || { echo "Pass PROMPT='...'"; exit 2; }
# 	@$(MOCKER) compose exec -f $(COMPOSE_FILE) -T codex-harness codex exec --skip-git-repo-check --json --sandbox workspace-write "$(PROMPT)"

# harness-logs: check ## Follow the Codex exec-server logs.
# 	@$(MOCKER) compose logs -f $(COMPOSE_FILE) --tail 200 codex-harness

container-down: check ## Stop and remove the stack.
	@$(MOCKER) compose down -f $(COMPOSE_FILE) --remove-orphans
