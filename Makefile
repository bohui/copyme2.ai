MOCKER ?= mocker
APPLE_CONTAINER_BIN ?= /opt/homebrew/bin/container
COMPOSE_FILE ?= compose.yml
API_PORT ?= 8010
WEB_PORT ?= 3010
API_BASE ?= http://127.0.0.1:$(API_PORT)
WEB_BASE ?= http://127.0.0.1:$(WEB_PORT)
SERVICE ?= api
EVAL_CASES ?= tests/evaluation/cases.json
EVAL_TASK ?= apps.api.evaluation_cases:run_case
EVAL_FAILURE_DIR ?= var/evaluation-failures
EVAL_CONCURRENCY ?= 1
CONTAINER_BUILD ?= 0
ENV_FILE ?= .env
CONTAINER_IMAGES := \
	localhost/memory-spark:dev \
	localhost/memory-spark-codex-worker:dev \
	localhost/copyme2-web:dev
SKILL_PACKAGER ?= $(HOME)/.codex/skills/skill-creator/scripts/package_skill.py
SKILLS ?= $(sort $(notdir $(patsubst %/SKILL.md,%,$(wildcard skills/*/SKILL.md))))

.PHONY: help check migrate db-truncate install_skill stripe_login setup_stripe setup_stripe_test setup_stripe_live runtime-start test langfuse-eval localization-catalog-test browser-test browser-localization-test browser-ten-round-test acceptance-evidence spec-audit persistence-check container-config container-build container-up container-health container-check container-ps container-logs container-shell container-down

help: ## Show the Apple Container + Mocker commands.
	@awk 'BEGIN {FS = ":.*##"; printf "\nMemory Spark — Apple Container + Mocker\n\nUsage: make <target>\n\n"} /^[a-zA-Z0-9][a-zA-Z0-9_.-]*:.*##/ {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

check: ## Verify Mocker and Apple Container are installed.
	@command -v $(MOCKER) >/dev/null || { echo "Missing Mocker. Install with: brew tap us/tap && brew install mocker"; exit 1; }
	@test -x "$(APPLE_CONTAINER_BIN)" || { echo "Missing Apple Container CLI: $(APPLE_CONTAINER_BIN)"; exit 1; }
	@echo "Mocker: $$($(MOCKER) --version)"
	@echo "Apple Container: $$($(APPLE_CONTAINER_BIN) --version)"

migrate: ## Apply the consolidated Supabase migration using tracked migration history.
	@set -a; \
	if test -f "$(ENV_FILE)"; then . "$(ENV_FILE)"; fi; \
	set +a; \
	test -n "$${SUPABASE_DB_URL:-}" || { echo "Set SUPABASE_DB_URL in .env."; exit 2; }; \
	command -v supabase >/dev/null || { echo "Missing Supabase CLI. Install it before running migrations."; exit 1; }; \
	supabase db push --db-url "$${SUPABASE_DB_URL}" --yes

db-truncate: check ## Permanently clear all app database rows, Supabase Auth users, every Storage bucket, local user files, and Compose data; pass RESET_CONFIRM=1.
	@test "$(RESET_CONFIRM)" = "1" || { echo "Refusing to truncate data. Re-run with RESET_CONFIRM=1."; exit 2; }
	@test -f "$(ENV_FILE)" || { echo "Missing $(ENV_FILE). Copy .env.example to .env first."; exit 2; }
	@set -a; \
	. "$(ENV_FILE)"; \
	set +a; \
	test -n "$${SUPABASE_DB_URL:-}" || { echo "Set SUPABASE_DB_URL in $(ENV_FILE)."; exit 2; }; \
	test -n "$${SUPABASE_URL:-}" || { echo "Set SUPABASE_URL in $(ENV_FILE)."; exit 2; }; \
	test -n "$${SUPABASE_SECRET_KEY:-$${SUPABASE_SERVICE_ROLE_KEY:-}}" || { echo "Set SUPABASE_SECRET_KEY (or SUPABASE_SERVICE_ROLE_KEY) in $(ENV_FILE)."; exit 2; }; \
	$(MOCKER) compose down -f $(COMPOSE_FILE) --remove-orphans --volumes; \
	python3 scripts/truncate_local_data.py --yes

install_skill: check ## Validate every repository skill, rebuild the skill-bearing app images, and restart their services.
	@set -eu; \
	test -n "$(strip $(SKILLS))" || { echo "No skills found under skills/."; exit 2; }; \
	test -f "$(SKILL_PACKAGER)" || { echo "Missing skill packager: $(SKILL_PACKAGER)"; echo "Override SKILL_PACKAGER=/path/to/package_skill.py if needed."; exit 1; }; \
	tmp_dir="$$(mktemp -d -t memory-spark-skills)"; \
	trap 'rm -rf "$$tmp_dir"' EXIT INT TERM; \
	for skill in $(SKILLS); do \
		test -d "skills/$$skill" || { echo "Missing skill directory: skills/$$skill"; exit 2; }; \
		python3 "$(SKILL_PACKAGER)" "skills/$$skill" "$$tmp_dir"; \
		archive="$$tmp_dir/$$skill.zip"; \
		test -f "$$archive" || { echo "Skill packager did not create $$archive"; exit 1; }; \
	done; \
	$(MOCKER) compose build -f $(COMPOSE_FILE) api codex-worker; \
	$(MOCKER) compose up -f $(COMPOSE_FILE) --no-build --force-recreate --detach --wait --wait-timeout 120 codex-worker api; \
	echo "Installed skills in api and codex-worker: $(SKILLS)"

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

langfuse-eval: ## Run the checked-in synthetic trajectory cases through the app/worker seam.
	@set -a; if test -f "$(ENV_FILE)"; then . "$(ENV_FILE)"; fi; set +a; \
	args=""; if test "$(EVAL_PUBLISH)" = "1"; then args="--publish"; fi; \
		python3 scripts/run_langfuse_evaluation.py --cases "$(EVAL_CASES)" --task "$(EVAL_TASK)" --failure-dir "$(EVAL_FAILURE_DIR)" --concurrency "$(EVAL_CONCURRENCY)" $$args

localization-catalog-test: ## Validate the English and Simplified Chinese message catalogues.
	@python3 scripts/check_localization_catalog.py

browser-test: ## Run the complete first-chapter Playwright journey against the Next.js frontend and API.
	@python3 /Users/bohuihan/.codex/skills/webapp-testing/scripts/with_server.py \
		--server "MEMORY_SPARK_TEST_MODE=1 MEMORY_SPARK_SHOW_THINKING_STEPS=0 python3 -m uvicorn apps.api.main:app --host 127.0.0.1 --port $(API_PORT)" \
		--port $(API_PORT) \
		--server "cd apps/web && MEMORY_SPARK_API_ORIGIN=http://127.0.0.1:$(API_PORT) npm run dev -- --hostname 127.0.0.1 --port $(WEB_PORT)" \
		--port $(WEB_PORT) -- python3 tests/browser_e2e.py --base-url http://127.0.0.1:$(WEB_PORT)

browser-localization-test: localization-catalog-test ## Run the browser localization journey against the Next.js frontend and API.
	@python3 /Users/bohuihan/.codex/skills/webapp-testing/scripts/with_server.py \
		--server "MEMORY_SPARK_TEST_MODE=1 MEMORY_SPARK_SHOW_THINKING_STEPS=1 python3 -m uvicorn apps.api.main:app --host 127.0.0.1 --port $(API_PORT)" \
		--port $(API_PORT) \
		--server "cd apps/web && MEMORY_SPARK_API_ORIGIN=http://127.0.0.1:$(API_PORT) npm run dev -- --hostname 127.0.0.1 --port $(WEB_PORT)" \
		--port $(WEB_PORT) -- python3 tests/browser_localization_e2e.py --base-url http://127.0.0.1:$(WEB_PORT)

browser-ten-round-test: localization-catalog-test ## Run ten localized chat turns with streaming and all integrated Memoir skills.
	@python3 /Users/bohuihan/.codex/skills/webapp-testing/scripts/with_server.py \
		--server "MEMORY_SPARK_TEST_MODE=1 MEMORY_SPARK_SHOW_THINKING_STEPS=0 python3 -m uvicorn apps.api.main:app --host 127.0.0.1 --port $(API_PORT)" \
		--port $(API_PORT) \
		--server "cd apps/web && MEMORY_SPARK_API_ORIGIN=http://127.0.0.1:$(API_PORT) npm run dev -- --hostname 127.0.0.1 --port $(WEB_PORT)" \
		--port $(WEB_PORT) -- python3 tests/browser_ten_round_e2e.py --base-url http://127.0.0.1:$(WEB_PORT) --locale all

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

container-up: runtime-start ## Start the local stack from cached images; use CONTAINER_BUILD=1 to rebuild.
	@mkdir -p var/memory-spark
	@set -e; \
	needs_build=0; \
	for image in $(CONTAINER_IMAGES); do \
		if ! $(MOCKER) image inspect "$$image" >/dev/null 2>&1; then \
			legacy_image=""; \
			case "$$image" in \
				localhost/memory-spark:dev) legacy_image=memory-spark:dev ;; \
				localhost/memory-spark-codex-worker:dev) legacy_image=memory-spark-codex-worker:dev ;; \
				localhost/copyme2-web:dev) legacy_image=copyme2-web:dev ;; \
				esac; \
			if test -n "$$legacy_image" && $(MOCKER) image inspect "$$legacy_image" >/dev/null 2>&1; then \
				$(MOCKER) tag "$$legacy_image" "$$image"; \
				echo "Tagged existing local image $$legacy_image as $$image"; \
			else \
				needs_build=1; \
			fi; \
		fi; \
	done; \
	if test "$(CONTAINER_BUILD)" = "1" || test "$$needs_build" = "1"; then \
		MEMORY_SPARK_CODEX_VERSION=$${MEMORY_SPARK_CODEX_VERSION:-0.156.1} $(MOCKER) compose build -f $(COMPOSE_FILE); \
	else \
		echo "Using cached service images; refreshing the web image from source."; \
		$(MOCKER) compose build -f $(COMPOSE_FILE) web; \
	fi
	@set -e; \
	set -a; if test -f "$(ENV_FILE)"; then . "$(ENV_FILE)"; fi; set +a; \
	$(MOCKER) compose down -f $(COMPOSE_FILE) --remove-orphans >/dev/null 2>&1 || true; \
	$(MOCKER) rm -f memory-spark-api-1 memory-spark-worker-1 memory-spark-web-1 memory-spark-codex-worker-1 memory-spark-temporal-1 memory-spark-photo-worker-1 >/dev/null 2>&1 || true; \
	$(MOCKER) compose up -f $(COMPOSE_FILE) --no-build --no-deps --detach temporal api worker web codex-worker photo-worker; \
	$(MOCKER) compose up -f $(COMPOSE_FILE) --no-build --no-recreate --no-deps --detach --wait --wait-timeout 120 temporal api worker web codex-worker photo-worker
	@$(MAKE) --no-print-directory container-health

container-health: check ## Verify API, web, Temporal, Codex and photo workers.
	@python3 scripts/verify_container_stack.py --api-base $(API_BASE) --web-base $(WEB_BASE) --expected-storage supabase-user-memory+filesystem-objects
	@$(MOCKER) compose exec -f $(COMPOSE_FILE) -T worker python scripts/worker.py --readiness
	@$(MOCKER) compose exec -f $(COMPOSE_FILE) -T photo-worker python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8767/health').read()"

container-check: ## Run the repository and specification checks locally.
	@$(MAKE) --no-print-directory acceptance-evidence
	@$(MAKE) --no-print-directory test
	@$(MAKE) --no-print-directory spec-audit

container-ps: check ## Show the running services.
	@$(MOCKER) ps --format '{{.Names}} {{.Status}}' | awk '$$1 ~ /^memory-spark-/'
	@$(MOCKER) compose ps -f $(COMPOSE_FILE)

container-logs: check ## Follow logs for SERVICE=api, web, codex-worker, photo-worker, or worker.
	@$(MOCKER) compose logs -f $(COMPOSE_FILE) --tail 200 $(SERVICE)

container-shell: check ## Open a shell in SERVICE=api.
	@$(MOCKER) compose exec -f $(COMPOSE_FILE) -it $(SERVICE) sh

container-down: check ## Stop and remove the stack.
	@$(MOCKER) compose down -f $(COMPOSE_FILE) --remove-orphans
