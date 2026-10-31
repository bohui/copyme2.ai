MOCKER ?= mocker
APPLE_CONTAINER_BIN ?= /opt/homebrew/bin/container
COMPOSE_FILE ?= compose.yml
.DEFAULT_GOAL := help

CONTAINER_REBUILD ?= 0
API_PORT ?= 8010
WEB_PORT ?= 3010
API_BASE ?= http://127.0.0.1:$(API_PORT)
WEB_BASE ?= http://127.0.0.1:$(WEB_PORT)
SERVICE ?= api
EVAL_CASES ?= tests/evaluation/cases.json
EVAL_TASK ?= apps.api.evaluation_cases:run_case
EVAL_FAILURE_DIR ?= var/evaluation-failures
EVAL_CONCURRENCY ?= 1
EVAL_SOURCE_REVISION ?= $(REVIEWED_MAIN_HEAD)
EVAL_CODEX_BINARY ?= $(REVIEWED_CODEX_BINARY)
EVAL_CODEX_SHA256 ?= $(REVIEWED_CODEX_SHA256)
EVAL_TEMPORAL_BINARY ?= $(REVIEWED_TEMPORAL_BINARY)
EVAL_TEMPORAL_SHA256 ?= $(REVIEWED_TEMPORAL_SHA256)
EVAL_CASE_ID ?=
EVAL_SOURCE_MODE ?= local
EVAL_RUN_ID ?=
EVAL_RUN_DIR ?=
EVAL_RESUME_DIR ?=
EVAL_ACCEPT_SOURCE_CHANGE ?= 0
EVAL_RECOVER_ACCEPTED_TURN ?= 0
EVAL_TIME_EXTENSION_SECONDS ?=
EVAL_EXTEND_UNTIL ?=
EVAL_OUTPUT_ROOT ?= $(HOME)/memoir-test-results
EVAL_MAX_CLIENT_REQUESTS ?= $(if $(strip $(EVAL_CASE_ID)),569,3000)
EVAL_MAX_ELAPSED_SECONDS ?= $(if $(strip $(EVAL_CASE_ID)),7200,36000)
EVAL_MAX_CASE_CLIENT_REQUESTS ?= $(if $(strip $(EVAL_CASE_ID)),569,600)
EVAL_MAX_CASE_ELAPSED_SECONDS ?= 7200
EVAL_USER_EMAIL ?= $(MEMOIR_EVAL_USER_EMAIL)
EVAL_START_BACKEND ?= 1
EVAL_MAX_BACKEND_REQUESTS ?= $(if $(strip $(EVAL_CASE_ID)),20000,100000)
EVAL_SETTLE_SECONDS ?= 600
EVAL_POLL_SECONDS ?= 2
EVAL_PROJECT_ID ?=
EVAL_PROGRESSIVE_RERUN ?= 0
MEMORY_SPARK_CODEX_WORKER_TIMEOUT ?= 240
ENV_FILE ?= .env
PROMPT_CREDENTIAL_FILE ?= $(HOME)/llm_provider/.env
PROMPT_NAME ?=
PROMPT_EVAL_NAME ?= memoir/skills/memoir-author-timeline/extract
PROMPT_EVAL_DATASET ?= memoir/evaluation/event-grounding
PROMPT_EVAL_VERSION ?=
PROMPT_EVAL_MODEL ?=
PROMPT_EVAL_PROVIDER_FILE ?= $(HOME)/llm_provider/.env
PROMPT_EVAL_RUN ?= 0
LIVE_SKILL ?=
LIVE_SKILL_CASE ?=
LIVE_SKILL_EFFORT ?= max
LIVE_SKILL_OUTPUT_ROOT ?= $(EVAL_OUTPUT_ROOT)/live-skills
TUNNEL_ARGS ?=
TUNNEL_CONFIG := $(CURDIR)/infra/cloudflare/config.yml
TUNNEL_LABEL := com.cloudflare.cloudflared.copyme2
SKILL_PACKAGER ?= $(HOME)/.codex/skills/skill-creator/scripts/package_skill.py
SKILLS ?= $(sort $(notdir $(patsubst %/SKILL.md,%,$(wildcard skills/*/SKILL.md))))

.PHONY: help check migrate db-reset db-truncate install_skill stripe_login setup_stripe setup_stripe_test setup_stripe_live runtime-start test langfuse-eval prompt-export prompt-check prompt-eval localization-catalog-test browser-test browser-localization-test browser-ten-round-test memoir-progressive-test acceptance-evidence spec-audit persistence-check container-config container-build container-up container-health container-check container-ps container-logs container-shell container-down
.PHONY: _db-truncate _install_skill _validate-skills _memoir-live-fifty-backend _container-up _container-down
.PHONY: memoir-live-skills-plan memoir-live-skills-test
.PHONY: prompt-sync prompt-sync-check prompt-sync-install
.PHONY: test-web test-place-research
.PHONY: deps-install deps-update

deps-install: ## Install the committed NovelToGame skill dependency without upgrading it.
	@git submodule update --init -- deps/novel-to-game
	@python3 scripts/snapshot_novel_game_dependency.py

deps-update: ## Update NovelToGame to upstream main; review and commit the new dependency pin.
	@git submodule update --init --remote --checkout -- deps/novel-to-game
	@python3 scripts/snapshot_novel_game_dependency.py

memoir-live-skills-plan: ## Inspect isolated skill contracts; zero model calls.
	@python3 scripts/run_memoir_live_skills.py $(if $(strip $(LIVE_SKILL)),--skill "$(LIVE_SKILL)",)

memoir-live-skills-test: ## Test every skill with real gateway calls and independent validators.
	@python3 scripts/run_memoir_live_skills.py --execute --env-file "$(ENV_FILE)" \
		--output-root "$(LIVE_SKILL_OUTPUT_ROOT)" --effort "$(LIVE_SKILL_EFFORT)" \
		$(if $(strip $(LIVE_SKILL)),--skill "$(LIVE_SKILL)",) \
		$(if $(strip $(LIVE_SKILL_CASE)),--case "$(LIVE_SKILL_CASE)",)

help: ## Show the Apple Container + Mocker commands.
	@awk 'BEGIN {FS = ":.*##"; printf "\nMemory Spark — Apple Container + Mocker\n\nUsage: make <target>\n\n"} \
		/^[a-zA-Z0-9][a-zA-Z0-9_.-]*:.*##/ {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2} \
		/^## / {hints[++hint_count] = substr($$0, 4)} \
		END {if (hint_count) printf "\n"; for (i = 1; i <= hint_count; i++) printf "%s\n", hints[i]}' $(MAKEFILE_LIST)

prompt-sync-install: ## Enable automatic prompt sync after main pulls in this clone.
	@python3 scripts/publish_langfuse_prompts.py --install-hook

prompt-sync: ## Publish changed prompts from the committed branch and refresh receipts.
	@python3 scripts/publish_langfuse_prompts.py --credential-file "$(PROMPT_CREDENTIAL_FILE)" $(if $(strip $(PROMPT_NAME)),--name "$(PROMPT_NAME)",)

prompt-sync-check: ## Check committed branch prompt changes without publishing.
	@python3 scripts/publish_langfuse_prompts.py --credential-file "$(PROMPT_CREDENTIAL_FILE)" --check $(if $(strip $(PROMPT_NAME)),--name "$(PROMPT_NAME)",)

prompt-export: ## Recovery: export published prompts; optional PROMPT_NAME=memoir/agents/mira/system.
	@python3 scripts/export_langfuse_prompts.py --credential-file "$(PROMPT_CREDENTIAL_FILE)" $(if $(strip $(PROMPT_NAME)),--name "$(PROMPT_NAME)",)

prompt-check: ## Verify repo prompt artifacts against their pinned Langfuse versions.
	@python3 scripts/export_langfuse_prompts.py --credential-file "$(PROMPT_CREDENTIAL_FILE)" --check $(if $(strip $(PROMPT_NAME)),--name "$(PROMPT_NAME)",)

prompt-eval: ## Preflight a pinned prompt and dataset; use PROMPT_EVAL_RUN=1 and PROMPT_EVAL_MODEL=... to call a model.
	@python3 scripts/evaluate_langfuse_prompt.py --credential-file "$(PROMPT_CREDENTIAL_FILE)" --provider-credential-file "$(PROMPT_EVAL_PROVIDER_FILE)" --name "$(PROMPT_EVAL_NAME)" --dataset "$(PROMPT_EVAL_DATASET)" $(if $(strip $(PROMPT_EVAL_VERSION)),--version "$(PROMPT_EVAL_VERSION)",) $(if $(strip $(PROMPT_EVAL_MODEL)),--model "$(PROMPT_EVAL_MODEL)",) $(if $(filter 1,$(PROMPT_EVAL_RUN)),--run,)

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

db-reset: ## Reset the disposable Supabase database from the consolidated baseline without seeding.
	@set -a; \
	if test -f "$(ENV_FILE)"; then . "$(ENV_FILE)"; fi; \
	set +a; \
	test -n "$${SUPABASE_DB_URL:-}" || { echo "Set SUPABASE_DB_URL in $(ENV_FILE)."; exit 2; }; \
	command -v supabase >/dev/null || { echo "Missing Supabase CLI. Install it before resetting the database."; exit 1; }; \
	supabase db reset --db-url "$${SUPABASE_DB_URL}" --no-seed --yes

db-truncate: ## Clear user/app data, Auth, Storage and local Compose state; preserve shared photo search cache; pass RESET_CONFIRM=1.
	@python3 scripts/backend_operation_lock.py -- $(MAKE) --no-print-directory _db-truncate

_db-truncate: check
	@test "$(RESET_CONFIRM)" = "1" || { echo "Refusing to truncate data. Re-run with RESET_CONFIRM=1."; exit 2; }
	@test -f "$(ENV_FILE)" || { echo "Missing $(ENV_FILE). Copy .env.example to .env first."; exit 2; }
	@set -a; \
	. "$(ENV_FILE)"; \
	set +a; \
	test -n "$${SUPABASE_DB_URL:-}" || { echo "Set SUPABASE_DB_URL in $(ENV_FILE)."; exit 2; }; \
	test -n "$${SUPABASE_URL:-}" || { echo "Set SUPABASE_URL in $(ENV_FILE)."; exit 2; }; \
	test -n "$${SUPABASE_SECRET_KEY:-$${SUPABASE_SERVICE_ROLE_KEY:-}}" || { echo "Set SUPABASE_SECRET_KEY (or SUPABASE_SERVICE_ROLE_KEY) in $(ENV_FILE)."; exit 2; }; \
	python3 scripts/truncate_local_data.py --check-scope || exit $$?; \
	$(MOCKER) compose down -f $(COMPOSE_FILE) --remove-orphans --volumes; \
	python3 scripts/truncate_local_data.py --yes

install_skill: ## Validate every repository skill, rebuild the skill-bearing app images, and restart their services.
	@python3 scripts/backend_operation_lock.py -- $(MAKE) --no-print-directory _install_skill

_install_skill: check deps-install _validate-skills
	@$(MOCKER) compose build -f $(COMPOSE_FILE) api codex-worker
	@set -e; \
	set -a; if test -f "$(ENV_FILE)"; then . "$(ENV_FILE)"; fi; set +a; \
	export MEMOIR_PUBLICATION_DATABASE_URL="$${MEMOIR_PUBLICATION_DATABASE_URL:-$${SUPABASE_DB_URL:-}}"; \
	$(MOCKER) compose up -f $(COMPOSE_FILE) --no-build --force-recreate --detach --wait --wait-timeout 120 codex-worker api
	@python3 scripts/refresh_mocker_compose_hosts.py --mocker "$(MOCKER)" --apple-container "$(APPLE_CONTAINER_BIN)" --compose-file "$(COMPOSE_FILE)"
	@echo "Installed skills in api and codex-worker: $(SKILLS)"

_validate-skills:
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
	done

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

test: test-web ## Run the local JavaScript and Python test suites.
	@python3 -m pytest -q

test-web: ## Run the web client regressions without a browser or external services.
	@node --test tests/js/*.test.mjs

test-place-research: test-web ## Replay the two-place interview through the API, database and web client.
	@python3 -c 'import os, shutil, sys; sys.exit(0 if os.getenv("MEMOIR_TEST_POSTGRES_BACKEND") in {"apple-container", "docker"} or (os.geteuid() != 0 and all(shutil.which(tool) for tool in ("initdb", "pg_ctl", "psql"))) else "Place regression requires local PostgreSQL tools and a non-root user, or MEMOIR_TEST_POSTGRES_BACKEND=apple-container/docker.")'
	@python3 -m pytest -q tests/test_place_research_context.py tests/test_place_photo_discovery.py tests/test_place_photo_browser.py \
		tests/test_place_groups.py tests/test_place_geocoding.py tests/test_place_photo_fallback.py \
		tests/test_place_photo_pages.py tests/test_place_photo_persistence.py tests/test_photo_worker.py \
		tests/test_lane_clarifications.py tests/test_timeline_reported_places.py \
		tests/test_timeline_context_confidence.py tests/test_timeline_estimates.py tests/test_timeline_place_repair.py tests/test_lifetime_memory_read_api.py \
		tests/test_lane_b_question_priorities.py tests/test_lane_b_question_priorities_postgres.py \
		tests/test_interview_guidance.py tests/test_interview_guidance_workflow.py tests/test_mira_realtime_interviewing.py \
		tests/test_recall_limit_questions.py tests/test_recall_limit_postgres.py \
		tests/test_two_lane_memory.py::test_confirmations_rank_first_and_survive_the_ordinary_hint_expiry \
		tests/test_two_lane_memory.py::test_confirmation_from_an_earlier_source_window_stays_queued \
		tests/test_background_skill_workflow.py::test_mira_asks_current_clarification_without_a_lane_b_pool_and_replays_once \
		tests/test_background_skill_workflow.py::test_model_recognized_control_stays_current_without_a_background_question_pool \
		tests/test_background_skill_workflow.py::test_restored_chengde_period_drives_both_photo_and_news_research \
		tests/test_database_baseline.py::test_one_fresh_baseline_has_no_upgrade_or_backfill_statements
	@python3 -m unittest discover -s skills/memoir-place-photo-research/tests

langfuse-eval: ## Replay fixed trajectory snapshots through the deterministic scorer.
	@set -a; if test -f "$(ENV_FILE)"; then . "$(ENV_FILE)"; fi; set +a; \
	args=""; if test "$(EVAL_PUBLISH)" = "1"; then args="--publish"; fi; \
		python3 scripts/run_langfuse_evaluation.py --cases "$(EVAL_CASES)" --task "$(EVAL_TASK)" --failure-dir "$(EVAL_FAILURE_DIR)" --concurrency "$(EVAL_CONCURRENCY)" $$args

.PHONY: memoir-live-fifty-plan memoir-live-fifty-test memoir-live-fifty-report memoir-live-fifty-login memoir-live-fifty-backend memoir-live-fifty-disposable-plan memoir-live-fifty-disposable-test

## Live memoir evaluation: each selected case runs a complete 50-round conversation.
##   Preview without LLM calls:
##     make memoir-live-fifty-plan EVAL_CASE_ID=harbour-copper-notebook
##   Run one case with live LLM calls:
##     make memoir-live-fifty-test EVAL_CASE_ID=harbour-copper-notebook
##     make memoir-live-fifty-test EVAL_CASE_ID=chengdu-tea-ledger
##     make memoir-live-fifty-test EVAL_CASE_ID=perth-workshop-compass
##     make memoir-live-fifty-test EVAL_CASE_ID=kunming-garden-lanterns
##     make memoir-live-fifty-test EVAL_CASE_ID=sydney-platform-letters
##   Omit EVAL_CASE_ID to run all five cases (250 rounds total).
##   Defaults: current checkout, remote Supabase from .env; stable case IDs select test@test.com through test5@test.com.
##   Creates/reuses all five confirmed test accounts with password test1234, without prompts.
##   Apply pending remote database changes after pulling: make migrate.
##   Starts backend services only; retains projects and prints UI URLs. No local PostgreSQL.
##   Refreshes service addresses and checks worker connections; make up is not required.
##   Sign in without email: make memoir-live-fifty-login (private ui-login.html).
##   Run the UI: MEMORY_SPARK_API_ORIGIN=http://127.0.0.1:8010 npm --prefix apps/web run dev -- --port 3010.
##   Sign in as EVAL_USER_EMAIL, then visit /memoir/interview/<project-id>.
##   db-truncate removes retained projects and Auth accounts; it never runs automatically.
##   Disposable alternative: make memoir-live-fifty-disposable-test EVAL_CASE_ID=<case>.
##   Saved report: ~/memoir-test-results/<run-id>/report.md (default location).
##   Regenerate: make memoir-live-fifty-report EVAL_RUN_DIR=/absolute/path/to/run
##   Setup details: docs/memoir-fifty-subscription-evaluation.md

memoir-live-fifty-plan: ## Inspect 50-round cases without LLM calls; select one with EVAL_CASE_ID.

memoir-live-fifty-test: memoir-test-accounts-setup ## Run 50 live rounds per case against remote Supabase; retain projects for the UI.

memoir-live-fifty-plan memoir-live-fifty-test:
	@set -eu; \
	test "$(EVAL_SOURCE_MODE)" = "local" || { echo "Remote evaluation tests the current checkout. Use the disposable target for reviewed-source mode." >&2; exit 2; }; \
	run_id="$(EVAL_RUN_ID)"; \
	if test -z "$(EVAL_RESUME_DIR)" && test -z "$$run_id"; then run_id="$$(python3 -c 'from uuid import uuid4; print(uuid4())')"; fi; \
	run_dir="$(if $(strip $(EVAL_RESUME_DIR)),$(abspath $(EVAL_RESUME_DIR)),$(EVAL_RUN_DIR))"; \
	if test -z "$$run_dir"; then run_dir="$(EVAL_OUTPUT_ROOT)/$$run_id"; fi; \
	set -- python3 scripts/run_memoir_supabase_evaluation.py \
		--run-dir "$$run_dir" --env-file "$(abspath $(ENV_FILE))" \
		--api-base "$(API_BASE)" --web-base "$(WEB_BASE)"; \
	if test -z "$(EVAL_RESUME_DIR)" || test "$(origin EVAL_MAX_ELAPSED_SECONDS)" != "file"; then set -- "$$@" --max-elapsed-seconds "$(EVAL_MAX_ELAPSED_SECONDS)"; fi; \
	if test -z "$(EVAL_RESUME_DIR)" || test "$(origin EVAL_MAX_CASE_ELAPSED_SECONDS)" != "file"; then set -- "$$@" --max-case-elapsed-seconds "$(EVAL_MAX_CASE_ELAPSED_SECONDS)"; fi; \
	if test -z "$(EVAL_RESUME_DIR)" || test "$(origin EVAL_MAX_BACKEND_REQUESTS)" != "file"; then set -- "$$@" --max-backend-requests "$(EVAL_MAX_BACKEND_REQUESTS)"; fi; \
	if test -z "$(EVAL_RESUME_DIR)" || test "$(origin EVAL_SETTLE_SECONDS)" != "file"; then set -- "$$@" --settle-seconds "$(EVAL_SETTLE_SECONDS)"; fi; \
	if test -z "$(EVAL_RESUME_DIR)" || test "$(origin EVAL_POLL_SECONDS)" != "file"; then set -- "$$@" --poll-seconds "$(EVAL_POLL_SECONDS)"; fi; \
	if test -n "$(EVAL_SOURCE_REVISION)"; then set -- "$$@" --source-revision "$(EVAL_SOURCE_REVISION)"; fi; \
	if test -n "$$run_id"; then set -- "$$@" --run-id "$$run_id"; fi; \
	if test -n "$(EVAL_RESUME_DIR)"; then set -- "$$@" --resume-dir "$(abspath $(EVAL_RESUME_DIR))"; fi; \
	case "$(EVAL_ACCEPT_SOURCE_CHANGE)" in 1) set -- "$$@" --accept-source-change ;; 0) ;; *) echo "EVAL_ACCEPT_SOURCE_CHANGE must be 0 or 1." >&2; exit 2 ;; esac; \
	case "$(EVAL_RECOVER_ACCEPTED_TURN)" in 1) set -- "$$@" --recover-accepted-turn ;; 0) ;; *) echo "EVAL_RECOVER_ACCEPTED_TURN must be 0 or 1." >&2; exit 2 ;; esac; \
	if test -n "$(EVAL_TIME_EXTENSION_SECONDS)"; then set -- "$$@" --extend-time-limit-seconds "$(EVAL_TIME_EXTENSION_SECONDS)"; fi; \
	if test -n "$(EVAL_EXTEND_UNTIL)"; then set -- "$$@" --extend-until "$(EVAL_EXTEND_UNTIL)"; fi; \
	if test -n "$(EVAL_CASE_ID)"; then set -- "$$@" --case-id "$(EVAL_CASE_ID)"; fi; \
	if test "$(EVAL_PROGRESSIVE_RERUN)" = "1"; then set -- "$$@" --progressive-rerun; fi; \
	if test "$@" = "memoir-live-fifty-plan"; then exec "$$@"; fi; \
	command -v node >/dev/null || { echo "Missing Node.js for the saved test report." >&2; exit 2; }; \
	case "$(EVAL_START_BACKEND)" in 1) set -- "$$@" --start-backend ;; 0) ;; *) echo "EVAL_START_BACKEND must be 0 or 1." >&2; exit 2 ;; esac; \
	set -- "$$@" --execute --create-confirmed-test-user; \
	status=0; MOCKER="$(MOCKER)" APPLE_CONTAINER_BIN="$(APPLE_CONTAINER_BIN)" COMPOSE_FILE="$(COMPOSE_FILE)" "$$@" || status=$$?; \
	if test -f "$$run_dir/receipt.json"; then \
		node scripts/render_memoir_subscription_report.mjs --run-dir "$$run_dir" || { if test "$$status" -eq 0; then status=1; fi; }; \
	fi; \
	exit "$$status"

memoir-live-fifty-login: ## Create/confirm EVAL_USER_EMAIL and save a private UI sign-in link; no email or LLM calls.
	@set -eu; \
	set -- python3 scripts/run_memoir_supabase_evaluation.py --prepare-user \
		--env-file "$(abspath $(ENV_FILE))" --web-base "$(WEB_BASE)"; \
	if test -z "$(EVAL_CASE_ID)" && test -n "$(EVAL_USER_EMAIL)"; then set -- "$$@" --user-email "$(EVAL_USER_EMAIL)"; fi; \
	if test -n "$(EVAL_CASE_ID)"; then set -- "$$@" --case-id "$(EVAL_CASE_ID)"; fi; \
	if test -n "$(EVAL_RUN_DIR)"; then set -- "$$@" --run-dir "$(EVAL_RUN_DIR)"; fi; \
	if test -n "$(EVAL_PROJECT_ID)"; then set -- "$$@" --project-id "$(EVAL_PROJECT_ID)"; fi; \
	exec "$$@"

memoir-live-fifty-backend: ## Start the API and workers for a remote run; called by memoir-live-fifty-test.
	@python3 scripts/backend_operation_lock.py -- $(MAKE) --no-print-directory _memoir-live-fifty-backend

_memoir-live-fifty-backend: runtime-start
	@test -n "$${MEMORY_SPARK_EVAL_RECALL_OWNER_ID:-}" || { echo "Use make memoir-live-fifty-test to configure its account allowance." >&2; exit 2; }
	@mkdir -p var/memory-spark
	@MEMORY_SPARK_CODEX_WORKER_TIMEOUT="$(MEMORY_SPARK_CODEX_WORKER_TIMEOUT)" $(MOCKER) compose up -f $(COMPOSE_FILE) --detach --no-build --force-recreate api codex-worker photo-worker worker temporal
	@python3 scripts/refresh_mocker_compose_hosts.py --mocker "$(MOCKER)" --apple-container "$(APPLE_CONTAINER_BIN)" --compose-file "$(COMPOSE_FILE)"
	@MEMORY_SPARK_CODEX_WORKER_TIMEOUT="$(MEMORY_SPARK_CODEX_WORKER_TIMEOUT)" $(MOCKER) compose up -f $(COMPOSE_FILE) --detach --no-build --no-recreate --wait --wait-timeout 120 api codex-worker photo-worker worker temporal
	@$(MOCKER) compose exec -f $(COMPOSE_FILE) -T api python -c 'import os,urllib.request; [urllib.request.urlopen(os.environ[key]+"/health", timeout=10).read() for key in ("MEMORY_SPARK_CODEX_WORKER_URL", "MEMORY_SPARK_PHOTO_WORKER_URL")]; print("API worker connections: ready")'
	@$(MOCKER) compose exec -f $(COMPOSE_FILE) -T worker python -c 'import os,urllib.request; urllib.request.urlopen(os.environ["MEMORY_SPARK_TASK_STORE_URL"]+"/health", timeout=10).read(); print("Worker API connection: ready")'
	@$(MOCKER) compose exec -f $(COMPOSE_FILE) -T worker python scripts/worker.py --readiness

memoir-live-fifty-disposable-plan: ## Inspect the original disposable PostgreSQL launcher without live calls.

memoir-live-fifty-disposable-test: ## Run the original disposable PostgreSQL evaluation; projects disappear after cleanup.

memoir-live-fifty-disposable-plan memoir-live-fifty-disposable-test:
	@set -eu; \
	case "$(EVAL_CASE_ID)" in \
		""|harbour-copper-notebook|chengdu-tea-ledger|perth-workshop-compass|kunming-garden-lanterns|sydney-platform-letters) ;; \
		*) echo "Unknown EVAL_CASE_ID. Choose harbour-copper-notebook, chengdu-tea-ledger, perth-workshop-compass, kunming-garden-lanterns or sydney-platform-letters." >&2; exit 2 ;; \
	esac; \
	case "$(EVAL_SOURCE_MODE)" in \
		local|reviewed) ;; \
		*) echo "EVAL_SOURCE_MODE must be local or reviewed." >&2; exit 2 ;; \
	esac; \
	source_revision="$(EVAL_SOURCE_REVISION)"; \
	codex_binary="$(EVAL_CODEX_BINARY)"; codex_sha256="$(EVAL_CODEX_SHA256)"; \
	temporal_binary="$(EVAL_TEMPORAL_BINARY)"; temporal_sha256="$(EVAL_TEMPORAL_SHA256)"; \
	if test -z "$$source_revision"; then source_revision="$$(git rev-parse HEAD)"; fi; \
	if test -z "$$codex_binary"; then codex_binary="$$(command -v codex || true)"; fi; \
	if test -z "$$temporal_binary"; then temporal_binary="$$(command -v temporal || true)"; fi; \
	if test -z "$$temporal_binary"; then temporal_binary="$$(python3 -c 'import os; from pathlib import Path; paths=[p for p in Path("/tmp/memoir-issue6-temporal").glob("temporal-sdk-python-*") if p.is_file() and os.access(p, os.X_OK)]; print(paths[0].resolve() if len(paths)==1 else "")')"; fi; \
	if test -n "$$codex_binary" && test -z "$$codex_sha256"; then codex_sha256="$$(python3 -c 'import hashlib,sys; from pathlib import Path; print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest())' "$$codex_binary")"; fi; \
	if test -n "$$temporal_binary" && test -z "$$temporal_sha256"; then temporal_sha256="$$(python3 -c 'import hashlib,sys; from pathlib import Path; print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest())' "$$temporal_binary")"; fi; \
	test -n "$$source_revision" || { echo "Cannot detect Git HEAD; set EVAL_SOURCE_REVISION." >&2; exit 2; }; \
	test -n "$$codex_binary" && test -n "$$codex_sha256" || { echo "Set EVAL_CODEX_BINARY and EVAL_CODEX_SHA256 (or REVIEWED_CODEX_*)." >&2; exit 2; }; \
	test -n "$$temporal_binary" && test -n "$$temporal_sha256" || { echo "Set EVAL_TEMPORAL_BINARY and EVAL_TEMPORAL_SHA256 (or REVIEWED_TEMPORAL_*); no unique cached Temporal executable was found." >&2; exit 2; }; \
	run_id="$(EVAL_RUN_ID)"; \
	if test -z "$$run_id"; then run_id="$$(python3 -c 'from uuid import uuid4; print(uuid4())')"; fi; \
	run_dir="$(EVAL_RUN_DIR)"; \
	if test -z "$$run_dir"; then run_dir="$(EVAL_OUTPUT_ROOT)/$$run_id"; fi; \
	set -- python3 scripts/run_issue14_subscription_evaluation.py \
		--evaluation-profile subscription_fifty \
		--run-id "$$run_id" --source-revision "$$source_revision" --run-dir "$$run_dir" \
		--codex-binary "$$codex_binary" --codex-sha256 "$$codex_sha256" \
		--temporal-binary "$$temporal_binary" --temporal-sha256 "$$temporal_sha256" \
		--max-client-requests "$(EVAL_MAX_CLIENT_REQUESTS)" --max-elapsed-seconds "$(EVAL_MAX_ELAPSED_SECONDS)" \
		--max-case-client-requests "$(EVAL_MAX_CASE_CLIENT_REQUESTS)" --max-case-elapsed-seconds "$(EVAL_MAX_CASE_ELAPSED_SECONDS)" \
		--collector-timeout-seconds 180; \
	if test "$(EVAL_SOURCE_MODE)" = "local"; then set -- "$$@" --local-checkout; fi; \
	if test -n "$(EVAL_CASE_ID)"; then set -- "$$@" --case-id "$(EVAL_CASE_ID)"; fi; \
	if test "$@" = "memoir-live-fifty-disposable-plan"; then exec "$$@"; fi; \
	command -v node >/dev/null || { echo "Missing Node.js for the saved test report." >&2; exit 2; }; \
	if test -f "$(ENV_FILE)"; then set -- "$$@" --existing-app-env "$(abspath $(ENV_FILE))"; fi; \
	set -- "$$@" --execute-existing-subscription; \
	printf 'Source mode: %s; commit: %s\n' "$(EVAL_SOURCE_MODE)" "$$source_revision" >&2; \
	if test -n "$(EVAL_CASE_ID)"; then \
		printf 'Case %s, 50 rounds. Evidence directory: %s\n' "$(EVAL_CASE_ID)" "$$run_dir" >&2; \
	else \
		printf 'Five cases, 50 rounds each. Evidence directory: %s\n' "$$run_dir" >&2; \
	fi; \
	status=0; "$$@" || status=$$?; \
	if test -f "$$run_dir/receipt.json"; then \
		node scripts/render_memoir_subscription_report.mjs --run-dir "$$run_dir" || { if test "$$status" -eq 0; then status=1; fi; }; \
	fi; \
	exit "$$status"

memoir-live-fifty-report: ## Render a saved live-run report; pass EVAL_RUN_DIR=/absolute/run-directory.
	@test -n "$(EVAL_RUN_DIR)" || { echo "Set EVAL_RUN_DIR to the saved run directory." >&2; exit 2; }
	@node scripts/render_memoir_subscription_report.mjs --run-dir "$(EVAL_RUN_DIR)"

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

memoir-progressive-test: localization-catalog-test ## Run 10 grounded 31-round memoir compositions plus China/Australia UI delivery checks.
	@node --test skills/memoir-composer/tests/*.test.mjs
	@python3 /Users/bohuihan/.codex/skills/webapp-testing/scripts/with_server.py \
		--server "MEMORY_SPARK_TEST_MODE=1 MEMORY_SPARK_SHOW_THINKING_STEPS=0 python3 -m uvicorn apps.api.main:app --host 127.0.0.1 --port $(API_PORT)" \
		--port $(API_PORT) \
		--server "cd apps/web && MEMORY_SPARK_API_ORIGIN=http://127.0.0.1:$(API_PORT) npm run dev -- --hostname 127.0.0.1 --port $(WEB_PORT) >/dev/null 2>&1" \
		--port $(WEB_PORT) -- python3 tests/browser_memoir_progressive_e2e.py --base-url http://127.0.0.1:$(WEB_PORT) --locale all

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
	@MEMORY_SPARK_CODEX_VERSION=$${MEMORY_SPARK_CODEX_VERSION:-0.156.1} $(MOCKER) compose build -f $(COMPOSE_FILE) api codex-worker web

.PHONY: up down

up: container-up ## Start the local stack, building changed images (alias for container-up).

.PHONY: recording-retention-enable
recording-retention-enable: ## Provision private recording storage and enable consent-gated STT without resetting data.
	@python3 scripts/backend_operation_lock.py -- $(MAKE) --no-print-directory _recording-retention-enable

.PHONY: _recording-retention-enable
_recording-retention-enable:
	@set -e; \
	memoir_env_file="$(ENV_FILE)"; case "$$memoir_env_file" in /*) ;; *) memoir_env_file="./$$memoir_env_file" ;; esac; \
	set -a; . "$$memoir_env_file"; set +a; \
	python3 scripts/setup_recording_retention.py --enable

container-up: ## Start local services and build changed images; CONTAINER_REBUILD=1 rebuilds all app images.
	@python3 scripts/backend_operation_lock.py -- $(MAKE) --no-print-directory _container-up

_container-up: runtime-start _validate-skills
	@python3 -B -m apps.api.prompt_artifact
	@mkdir -p var/memory-spark
	@mkdir -p var/memory-spark/objects/story-game-scenes
	@set -e; \
	memoir_env_file="$(ENV_FILE)"; case "$$memoir_env_file" in /*) ;; *) memoir_env_file="./$$memoir_env_file" ;; esac; \
	set -a; if test -f "$$memoir_env_file"; then . "$$memoir_env_file"; fi; set +a; \
	export MEMOIR_PUBLICATION_DATABASE_URL="$${MEMOIR_PUBLICATION_DATABASE_URL:-$${SUPABASE_DB_URL:-}}"; \
	python3 scripts/start_container_stack.py --mocker "$(MOCKER)" --apple-container "$(APPLE_CONTAINER_BIN)" \
		--compose-file "$(COMPOSE_FILE)" $(if $(filter 1,$(CONTAINER_REBUILD)),--force-build,) \
		-- $(MAKE) --no-print-directory container-health

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

down: container-down ## Stop and remove the stack (alias for container-down).

container-down: ## Stop and remove the stack.
	@python3 scripts/backend_operation_lock.py -- $(MAKE) --no-print-directory _container-down

_container-down: check
	@$(MOCKER) compose down -f $(COMPOSE_FILE) --remove-orphans

.PHONY: cloudflare-link cloudflare-unlink tunnel-plan tunnel-setup tunnel-start tunnel-stop tunnel-status tunnel-health

cloudflare-link: tunnel-start ## Link copyme2.ai to the local frontend on port 3010.

cloudflare-unlink: tunnel-stop ## Disconnect copyme2.ai from this Mac until linked again.

tunnel-plan: ## Preview the copyme2.ai Cloudflare Tunnel setup.
	@set -a; if test -f "$(ENV_FILE)"; then . "$(ENV_FILE)"; fi; set +a; scripts/setup-cloudflare-tunnel.sh

tunnel-setup: ## Configure CopyMe2 DNS and install its launch agent; pass TUNNEL_ARGS=--replace-existing for the first cutover.
	@set -a; if test -f "$(ENV_FILE)"; then . "$(ENV_FILE)"; fi; set +a; scripts/setup-cloudflare-tunnel.sh --apply $(TUNNEL_ARGS)

tunnel-start: ## Install/start the tunnel launch agent using its existing local config.
	@set -a; if test -f "$(ENV_FILE)"; then . "$(ENV_FILE)"; fi; set +a; scripts/setup-cloudflare-tunnel.sh --service-only

tunnel-stop: ## Stop the CopyMe2 connector and disable its automatic start at login.
	@set -eu; \
	service="gui/$$(id -u)/$(TUNNEL_LABEL)"; \
	launchctl disable "$$service"; \
	if launchctl print "$$service" >/dev/null 2>&1; then \
		launchctl bootout "$$service"; \
	fi; \
	echo "CopyMe2 tunnel disconnected. Reconnect with: make cloudflare-link"

tunnel-status: ## Show the CopyMe2 launch agent state and ingress validation.
	@launchctl print gui/$$(id -u)/$(TUNNEL_LABEL)
	@cloudflared tunnel --config "$(TUNNEL_CONFIG)" ingress validate

tunnel-health: ## Verify the public landing page, Memoir route, and API proxy.
	@curl --fail --silent --show-error --max-time 30 --output /dev/null https://copyme2.ai/
	@curl --fail --silent --show-error --max-time 30 --output /dev/null https://copyme2.ai/memoir/start
	@curl --fail --silent --show-error --max-time 30 https://copyme2.ai/api/v1/memoir/config | python3 -c 'import json,sys; assert json.load(sys.stdin)["product"] == "Memory Spark"; print("CopyMe2 public web and API proxy: healthy")'

# Always prepare the five selected Auth accounts before the existing live target.
MEMOIR_TEST_ACCOUNTS_PYTHON ?= python3
.PHONY: memoir-test-accounts-plan memoir-test-accounts-setup

memoir-test-accounts-plan: ## Read-only selected test-account inventory; no Auth writes.
	@"$(MEMOIR_TEST_ACCOUNTS_PYTHON)" scripts/setup_memoir_test_accounts.py --env-file "$(abspath $(ENV_FILE))"

memoir-test-accounts-setup: ## Ensure five confirmed test accounts with password test1234; no prompts.
	@"$(MEMOIR_TEST_ACCOUNTS_PYTHON)" scripts/setup_memoir_test_accounts.py --env-file "$(abspath $(ENV_FILE))" --apply
