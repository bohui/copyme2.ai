# Test-account setup before each fifty-round run

`memoir-live-fifty-test` has the phony prerequisite `memoir-test-accounts-setup`.
It checks the complete Supabase Auth inventory before each invocation, including
selected-case runs and the existing all-five-case command:

```sh
make memoir-live-fifty-test
make memoir-live-fifty-test EVAL_CASE_ID=harbour-copper-notebook
```

The setup covers exactly `test@test.com`, `test2@test.com`, `test3@test.com`,
`test4@test.com`, and `test5@test.com` in project `vpzhimeqmuzyzfozcjnq`.
All five use password `test1234` and have confirmed email addresses, so they can
sign in immediately. Setup runs unattended: no approval phrase or password input.
It creates missing accounts and updates existing accounts in place with the same
test password and email confirmation. Each run enforces these credentials;
existing IDs, metadata and application data are preserved. It never signs in,
sends email, deletes accounts or creates login links.

Reruns reuse the same five identities, including accounts created during a
partially completed setup. A failed or uncertain write stops setup and prevents
the test recipe from starting; it is reconciled by reading the inventory and is
not retried within that invocation. No password override is accepted through
arguments, environment variables or files.

Standalone commands:

```sh
make memoir-test-accounts-plan   # Read-only inventory and proposed actions.
make memoir-test-accounts-setup  # Ensure the five confirmed test accounts, without prompts.
```

Use the existing private `ENV_FILE` (default `.env`), owned by the current user
with mode `0400` or `0600`; symlinks are refused. It needs `SUPABASE_URL` and
`SUPABASE_SECRET_KEY` or `SUPABASE_SERVICE_ROLE_KEY`. The URL must match the
selected HTTPS project. Credentials and account passwords are never printed.
If needed, select an existing Python environment containing `python-dotenv`:

```sh
make memoir-live-fifty-test MEMOIR_TEST_ACCOUNTS_PYTHON=/absolute/path/to/python
```

The live runner uses a fixed case-to-account mapping:

| Case ID | Account | Password |
| --- | --- | --- |
| harbour-copper-notebook | test@test.com | test1234 |
| chengdu-tea-ledger | test2@test.com | test1234 |
| perth-workshop-compass | test3@test.com | test1234 |
| kunming-garden-lanterns | test4@test.com | test1234 |
| sydney-platform-letters | test5@test.com | test1234 |

It verifies distinct owners and each case's session
and canonical project. See `docs/memoir-fifty-subscription-evaluation.md` for
canonical reuse, resume, per-case login files and manual execution. The setup
prerequisite remains account-only and is not evidence that runtime/schema or
live model execution is ready.

Offline validation:

```sh
python -m pytest -q tests/test_setup_memoir_test_accounts.py
make -n memoir-live-fifty-test
```

Tests use fictional account credentials and block real HTTP. Make ordering is
tested using a temporary fixture Makefile and stub scripts, never live services.
