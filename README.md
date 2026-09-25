# CopyMe2

CopyMe2 is the platform umbrella: **preserve the parts of you that matter**. The first live product is Memoir, a guided, source-linked memoir journey that turns memories, photographs, and the storyteller's own voice into a family book.

## Product URLs

The public URL structure is product-scoped so future products can live beside Memoir:

```text
copyme2.ai/
├── memoir/                  # live Memoir product
│   ├── start
│   ├── my-story
│   ├── interview/:sessionId
│   ├── memories/:id
│   ├── diary
│   ├── photos
│   ├── people
│   ├── timeline
│   ├── chapters/:id
│   ├── preview
│   ├── package
│   ├── checkout
│   ├── book
│   ├── print
│   ├── settings
│   └── family/{people,review}
└── voice/                   # reserved for a future product
```

The browser prototype serves the platform landing page at `/`, the Memoir entry page at `/memoir`, and the interview/workspace shell from the Memoir routes. Direct links are handled by the web shell so the route shape is ready for a future framework-backed frontend.

## Repository layout

```text
apps/
├── api/                    # FastAPI application and Supabase user-data adapters
│   ├── main.py             # Memoir HTTP interface
│   ├── story_payments.py   # Stripe Checkout and server-side entitlements
│   ├── store.py            # Project, session, memory, chapter, and edition state
│   └── namespaces.py       # /api/v1/memoir compatibility seam
└── web/
    ├── app/
    │   ├── routes.js       # platform and Memoir route catalog
    │   └── memoir/client.js # current vanilla SPA implementation
    └── public/             # deployable HTML and CSS shell
docs/                       # product specification and implementation notes
supabase/                   # database migrations
tests/                      # API, workflow, persistence, and browser checks
```

Domain entities remain product-neutral (`Project`, `MemorySession`, `Memory`, `Chapter`, and `Edition`). The URL namespace is the product seam; it does not leak `/memoir` into database names.

## API namespace

Memoir's canonical API is:

```text
/api/v1/memoir/projects
/api/v1/memoir/memory-sessions
/api/v1/memoir/memories
/api/v1/memoir/people
/api/v1/memoir/chapters
/api/v1/memoir/editions
```

The existing `/v1/...` interface remains as a backwards-compatible adapter for the current specification tests and older clients. Both paths use the same implementation and domain store.

## Run locally

The connected story journey uses Supabase Auth, RLS-protected `user_profile`/`user_memory` rows, and the private `memory-spark` Storage bucket. The legacy specification routes retain an explicit in-memory adapter while they are being retired; there is no application-owned Postgres state store.

```bash
MEMORY_SPARK_TEST_MODE=1 python3 -m uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Configure `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`, then enable **Allow manual linking** and **Allow anonymous sign-ins** under Supabase Auth → Sign In / Providers. Configure both Google and Facebook there as well; the browser uses Supabase `linkIdentity` after round five. See [Supabase anonymous sign-ins](https://supabase.com/docs/guides/auth/auth-anonymous) and [manual identity linking](https://supabase.com/docs/guides/auth/auth-identity-linking#manual-linking-beta).

## Story packages and Stripe

After the free first chapter, the story journey offers three one-time packages in Australian dollars:

| Package | Price | Includes |
| --- | ---: | --- |
| Electronic memoir | A$29 | Electronic version only |
| Printed memoir | A$59 | Electronic version and 2 printed books |
| Family legacy memoir | A$99 | Electronic version, 2 printed books, family tree, timeline, and more detailed story context |

Additional printed books cost A$10 each for either printed package. The API calculates the total from the selected package and quantity; the browser cannot set the amount. Stripe Checkout is hosted by Stripe, and the paid entitlement is granted only by the signed webhook at `/api/v1/memoir/story/stripe/webhook` after a successful `checkout.session.completed` or asynchronous payment event.

Set these values in `.env` for a real checkout:

```text
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
SUPABASE_SECRET_KEY=your-server-only-supabase-secret
MEMORY_SPARK_PUBLIC_URL=https://your-domain.example
```

`STRIPE_PRICE_ELECTRONIC`, `STRIPE_PRICE_PRINTED`, `STRIPE_PRICE_FAMILY`, and `STRIPE_PRICE_ADDITIONAL_BOOK` are optional Dashboard-created Price IDs. If they are blank, the server uses Stripe `price_data` with the fixed server-side amounts. Never expose `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, or `SUPABASE_SECRET_KEY` to the browser.

Register the webhook URL in Stripe Workbench for `checkout.session.completed` and `checkout.session.async_payment_succeeded`. For local testing, forward events with the Stripe CLI:

```bash
stripe listen --forward-to 127.0.0.1:8000/api/v1/memoir/story/stripe/webhook
```

## Run with Apple Container and Mocker

```bash
make container-config
make container-up
make container-health
make container-ps
make container-logs SERVICE=api
make container-down
```

The default ports are `http://127.0.0.1:3010` for the web shell, `http://127.0.0.1:8010` for the API, and `ws://127.0.0.1:8765` for the Codex harness. Override them with `MEMORY_SPARK_WEB_PORT`, `MEMORY_SPARK_API_PORT`, and `MEMORY_SPARK_CODEX_HARNESS_PORT`. The API image is defined by [`Containerfile`](Containerfile); Codex runtime execution is in the private [`codex-worker/Containerfile`](codex-worker/Containerfile); the browser proxy is [`infra/nginx/memory-spark.conf`](infra/nginx/memory-spark.conf).

The API uses the user's Supabase bearer token for RLS-protected story and Codex-memory operations. Codex runs only in the private worker container, which uses a dedicated volume and per-user OS identities; the API sends it only the already-authorized memory context. Set `MEMORY_SPARK_CODEX_WORKER_SECRET` to a long random value outside local development. Private original/generated blobs remain below `var/memory-spark/objects`. Copy `.env.example` to `.env` and configure Supabase and the local LLM provider before using the connected Codex agent.

Manual Google Web OAuth and Supabase Google sign-in setup is documented in [`gcp/google_oauth.md`](gcp/google_oauth.md). The standard Web OAuth client is created in Google Cloud Console and the client secret is stored in Supabase, not in the browser.

Apply the checked-in migrations before using the connected agent:

```bash
psql "<your Supabase Postgres connection string>" -f supabase/migrations/202609230001_user_agent_storage.sql
psql "<your Supabase Postgres connection string>" -f supabase/migrations/202609230002_agent_sessions.sql
psql "<your Supabase Postgres connection string>" -f supabase/migrations/202609250002_agent_turn_leases.sql
psql "<your Supabase Postgres connection string>" -f supabase/migrations/202609250003_story_entitlements.sql
```

For an installation that previously applied the retired JSONB-state migration, run `supabase/migrations/202609250001_remove_memory_spark_state.sql` once with your normal Supabase migration connection. It drops only the retired `memory_spark_state` and `memory_spark_outbox` tables.

## Verify

```bash
python3 -m pytest -q
make browser-test
python3 scripts/run_acceptance_evidence.py
python3 scripts/audit_spec_routes.py
```

The full implementation covers consent, invitations, resumable uploads, cue reactions, evidence-linked memories, version conflicts, preview builds, checkout and verified webhooks, chapters, editions, audio links, print proofs, deletion tombstones, audit metadata, regional provider switches, Supabase persistence, and the Codex memory integration. Production merchant, regional processor, media-rights, supplier, legal, and reliability gates remain configuration and operations decisions outside this credential-free local implementation.
