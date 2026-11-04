# Database migrations

Until the user explicitly announces production deployment, keep all schema
changes in `supabase/migrations/202610180001_initial_schema.sql`. Update that
single fresh-install baseline in place instead of adding migration files.

# Regression checks

For place/photo/news research or workspace localization changes, run
`make test-place-research` before reporting completion. Keep its API-to-client
replay covering the reported failure; `python3 -m pytest` alone omits web tests.

# Prompt governance

For prompt additions, edits, shared-component changes or retirement, read the
[prompt evaluation workflow](docs/prompt-evaluation-workflow.md) and update
`config/prompt-coverage.json`. Review the affected dataset cases and evaluators
together; record why either can be reused when no change is needed. Refresh the
inventory with `make prompt-coverage` and run `make prompt-check` plus the relevant
scenario regressions. A configured dataset or passing contract test does not
establish quality for an unverified prompt version.

Before creating or changing any model prompt, including shared components, read
the [versioned prompt workflow](README.md#versioned-prompt-artifacts).

Commit prompt Markdown before running `make prompt-sync` on the current branch;
feature branches can publish before merging. The publisher creates a version
only for changed content and refreshes the matching `.langfuse.json` receipt.
Review and commit generated receipts with the prompt changes, then run
`make prompt-check` to verify published pins. Never invent a published version.
The installed Git hook automatically syncs only after pulls on `main`, which
must match `origin/main` before publication.
