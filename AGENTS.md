# Database migrations

Until the user explicitly announces production deployment, keep all schema
changes in `supabase/migrations/202610180001_initial_schema.sql`. Update that
single fresh-install baseline in place instead of adding migration files.

# Regression checks

For place/photo/news research or workspace localization changes, run
`make test-place-research` before reporting completion. Keep its API-to-client
replay covering the reported failure; `python3 -m pytest` alone omits web tests.

# Prompt governance

Before creating or changing any model prompt, including shared components, read
the [versioned prompt workflow](README.md#versioned-prompt-artifacts).

Commit prompt Markdown before running `make prompt-sync` on the current branch;
feature branches can publish before merging. The publisher creates a version
only for changed content and refreshes the matching `.langfuse.json` receipt.
Review and commit generated receipts with the prompt changes, then run
`make prompt-check` to verify published pins. Never invent a published version.
The installed Git hook automatically syncs only after pulls on `main`, which
must match `origin/main` before publication.
