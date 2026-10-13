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
Existing accounts are reused. The setup never resets a password, deletes data,
changes existing confirmation flags, signs in, sends email, or creates login links.
If all five exist, it performs reads only and needs no interactive input.

If an account is missing, the human must use an interactive terminal, type
`APPLY vpzhimeqmuzyzfozcjnq FIVE TEST ACCOUNTS`, and enter each missing user's
password twice through hidden input. New users are created unconfirmed.
Refused approval, unavailable hidden input, cancellation, or an uncertain write
stops setup and prevents the test recipe from starting. Earlier successful
creations remain; the next invocation rechecks the inventory and reuses them.
No password can be passed through arguments, environment variables or files.

Standalone commands:

```sh
make memoir-test-accounts-plan   # Read-only inventory and proposed actions.
make memoir-test-accounts-setup  # Human-approved creation of missing users only.
```

Use the existing private `ENV_FILE` (default `.env`), owned by the current user
with mode `0400` or `0600`; symlinks are refused. It needs `SUPABASE_URL` and
`SUPABASE_SECRET_KEY` or `SUPABASE_SERVICE_ROLE_KEY`. The URL must match the
selected HTTPS project. Credentials and account passwords are never printed.
If needed, select an existing Python environment containing `python-dotenv`:

```sh
make memoir-live-fifty-test MEMOIR_TEST_ACCOUNTS_PYTHON=/absolute/path/to/python
```

The live runner uses a fixed case-to-account mapping: harbour → `test@test.com`,
chengdu → `test2@test.com`, perth → `test3@test.com`, kunming → `test4@test.com`,
sydney → `test5@test.com`. It verifies distinct owners and each case's session
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
