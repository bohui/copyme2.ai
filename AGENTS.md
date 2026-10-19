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

Review prompt Markdown in Git and merge it to `main` before publishing. Do not
create Langfuse versions from feature branches. After pulling `main`, the
installed Git hook runs `make prompt-sync`'s publisher, which creates a version
only for changed content and refreshes the matching `.langfuse.json` receipt.
Use `make prompt-sync` to retry and `make prompt-check` to verify published pins.
Review and commit generated receipt updates; never invent a published version.
