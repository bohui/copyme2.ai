# Stripe payment setup

This document covers the Stripe Checkout integration for the memoir packages. The API creates one-time hosted Checkout Sessions, calculates the payable amount from a server-side plan key and book count, and grants the paid entitlement only after a verified Stripe webhook.

## Product catalog

All amounts are in Australian dollars (AUD).

| Plan key | Customer-facing package | Base price | Included | Extra printed books |
| --- | --- | ---: | --- | ---: |
| `electronic_memoir_v1` | Electronic memoir | A$49 | Electronic memoir, source-linked chapters, private digital delivery | Not available |
| `printed_memoir_v1` | Printed memoir | A$79 | Electronic memoir plus 2 printed books | A$10 each |
| `family_memoir_v1` | Family legacy memoir | A$129 | Electronic memoir, 2 printed books, family tree, life timeline, and more detailed story context | A$10 each |

The printed packages accept 2–20 books. The API calculates the amount:

```text
total = package price + (book count - 2) × A$10
```

The browser cannot set the amount directly. The API derives it from the selected plan and validates the amount again when processing the webhook.

## Prerequisites

You need:

- A Stripe account with access to test mode and, for production, live mode.
- A Supabase project used by the API.
- A deployed API URL that Stripe can reach over HTTPS for the production webhook.
- The memoir application’s public URL, used for Stripe success and cancellation redirects.

## Setup script

`infra/stripe/setup_stripe.py` creates or reuses the four one-time Stripe products and prices from the server-side catalog. It imports the catalog from `apps/api/story_payments.py`, so it does not maintain a second set of amounts.

Preview the resources without contacting Stripe:

```bash
make setup_stripe_test \
  STRIPE_SECRET_KEY=sk_test_... \
  STRIPE_SETUP_ARGS=--dry-run
```

Create or reuse test-mode products and prices:

```bash
make setup_stripe_test STRIPE_SECRET_KEY=sk_test_...
```

For the live catalog, provide the live secret key and public application URL. The Makefile creates the production webhook URL by appending `/api/v1/memoir/story/stripe/webhook`:

```bash
make setup_stripe_live \
  STRIPE_SECRET_KEY=sk_live_... \
  MEMORY_SPARK_PUBLIC_URL=https://<public-domain>
```

The two targets pass the explicitly supplied key through the process environment, validate its mode prefix, construct `STRIPE_WEBHOOK_URL` from `MEMORY_SPARK_PUBLIC_URL`, pass `--yes` to the idempotent setup script, and write the key, computed webhook URL, generated Price IDs, and (when a new webhook is created) `STRIPE_WEBHOOK_SECRET` to `infra/stripe/stripe_env_config_<mode>.txt`. These files are local-only, mode `0600`, and ignored by Git. Pass additional script flags with `STRIPE_SETUP_ARGS`, for example `STRIPE_SETUP_ARGS="--dry-run"`.

`STRIPE_WEBHOOK_URL` is generated for either target when `MEMORY_SPARK_PUBLIC_URL` is supplied. You can still override it with a complete `STRIPE_WEBHOOK_URL`. Omit both for test mode when using `stripe listen` for local forwarding. Live mode requires a real public HTTPS endpoint. `make stripe_login` remains available for local Stripe CLI webhook forwarding, but is not required by these setup targets. If an existing webhook is reused, Stripe does not return its signing secret; retrieve the existing `whsec_...` value from Stripe Dashboard or the API environment.

## 1. Apply the Supabase entitlement migration

Payment state is stored separately from the user-editable memoir profile in `public.story_entitlements`. Apply the migration once to each Supabase database:

```bash
psql "<your Supabase Postgres connection string>" \
  -f supabase/migrations/202609250003_story_entitlements.sql
```

The API uses `SUPABASE_SECRET_KEY` for server-side entitlement writes. Keep this key on the API service only; never expose it in browser code.

## 2. Configure Stripe products and prices

The integration supports two equivalent configurations.

### Option A: Dashboard-created Price IDs

Create four one-time prices in Stripe Dashboard:

| Stripe product/price | Currency and amount | Environment variable |
| --- | ---: | --- |
| Electronic memoir | AUD 4900 cents | `STRIPE_PRICE_ELECTRONIC` |
| Printed memoir base package | AUD 7900 cents | `STRIPE_PRICE_PRINTED` |
| Family legacy memoir base package | AUD 12900 cents | `STRIPE_PRICE_FAMILY` |
| Additional printed book | AUD 1000 cents | `STRIPE_PRICE_ADDITIONAL_BOOK` |

For the two printed packages, the Checkout Session contains the base price plus the additional-book price with a quantity equal to the number of books above two. For example, four printed books produce one base line item and two additional-book units.

If a configured Price ID has the wrong currency or amount, the webhook rejects the order with `STRIPE_ORDER_MISMATCH`. Keep the Dashboard prices aligned with the server-side catalog above.

### Option B: Server-generated `price_data`

Leave the four `STRIPE_PRICE_*` variables blank. The API then sends the fixed server-side amounts as inline Stripe `price_data` when it creates each Checkout Session. This is convenient for an initial integration or test deployment.

## 3. Configure environment variables

Copy the relevant values into the API environment. The values below are placeholders:

```dotenv
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SECRET_KEY=<server-only-supabase-secret-key>

STRIPE_SECRET_KEY=sk_test_<stripe-test-secret-key>
STRIPE_WEBHOOK_SECRET=whsec_<endpoint-signing-secret>

# Optional Dashboard-created one-time Price IDs.
STRIPE_PRICE_ELECTRONIC=
STRIPE_PRICE_PRINTED=
STRIPE_PRICE_FAMILY=
STRIPE_PRICE_ADDITIONAL_BOOK=

MEMORY_SPARK_PUBLIC_URL=https://<public-app-domain>
MEMORY_SPARK_PRINT_COUNTRIES=AU

# Optional overrides. The defaults point to the memoir start page.
STRIPE_SUCCESS_URL=
STRIPE_CANCEL_URL=
```

For local development, `MEMORY_SPARK_PUBLIC_URL` can be `http://localhost:3010`. If `STRIPE_SUCCESS_URL` and `STRIPE_CANCEL_URL` are blank, the API uses:

```text
<public-url>/memoir/start?checkout=success&session_id={CHECKOUT_SESSION_ID}
<public-url>/memoir/start?checkout=cancelled
```

Printed packages request a shipping address from the countries listed in `MEMORY_SPARK_PRINT_COUNTRIES`. Keep the list restricted to countries the fulfillment process supports.

## 4. Register the Stripe webhook

Create a webhook endpoint in Stripe Dashboard using the URL below, or let the setup script create/synchronize it with `--webhook-url`:

```text
https://<api-domain>/api/v1/memoir/story/stripe/webhook
```

Subscribe to these events:

- `checkout.session.completed`
- `checkout.session.async_payment_succeeded`

Copy the endpoint’s signing secret, which begins with `whsec_`, into `STRIPE_WEBHOOK_SECRET` on the API service. The endpoint must receive the unmodified request body because signature verification is performed against the raw payload.

The handler ignores unrelated event types, verifies the Stripe signature, validates the plan metadata, validates the amount and currency, and then records the entitlement in `story_entitlements`. A success redirect by itself does not unlock the full memoir.

### Why a webhook is still required for one-time products

One-time products do not need subscription events such as `customer.subscription.updated` or `invoice.paid`, but this application still needs a webhook. The browser’s success redirect is not proof of payment, and payment confirmation can arrive after the redirect or be retried by Stripe. The signed webhook is the server-to-server source of truth that grants the entitlement and prevents a client from unlocking a paid memoir by editing browser state. For this integration, the two Checkout Session events above are sufficient; subscription lifecycle events are not required.

## 5. Test locally

Install and authenticate the Stripe CLI, then forward Stripe events to the local API:

```bash
stripe login
stripe listen \
  --forward-to 127.0.0.1:8000/api/v1/memoir/story/stripe/webhook
```

The CLI prints a temporary `whsec_...` signing secret. Use that value as `STRIPE_WEBHOOK_SECRET` for the local process, and use a Stripe test-mode key beginning with `sk_test_` as `STRIPE_SECRET_KEY`.

Start the API and web app, choose a package, and complete Checkout with a Stripe test card. Stripe’s [testing documentation](https://docs.stripe.com/testing) has the current test cards and payment-method scenarios.

After a successful test payment:

1. Stripe sends `checkout.session.completed` to the forwarded endpoint.
2. The API verifies the event and writes the paid entitlement.
3. The memoir page can then load the paid state and the full memoir features.

If the payment is asynchronous, the entitlement is finalized when `checkout.session.async_payment_succeeded` arrives.

## API endpoints

The browser uses these routes:

```text
GET  /api/v1/memoir/story/plans
POST /api/v1/memoir/story/checkout
POST /api/v1/memoir/story/stripe/webhook
```

The application router also exposes the same story routes under `/v1/story/...` for direct API use. Checkout requires an authenticated, linked account and a claimed free chapter. The checkout request selects a `plan_key` and, for printed packages, an optional `book_count`.

## Verification

Check that the catalog is available:

```bash
curl http://127.0.0.1:8000/api/v1/memoir/story/plans
```

Run the repository checks after changing the payment flow:

```bash
python3 -m pytest -q
python3 -m compileall -q apps
node --check apps/web/app/memoir/client.js
git diff --check
```

The automated tests cover plan pricing, quantity calculation, Checkout Session construction, signature verification, webhook idempotency, amount validation, and entitlement persistence.

## Troubleshooting

| Symptom or error code | Likely cause | Fix |
| --- | --- | --- |
| `STRIPE_NOT_CONFIGURED` | `STRIPE_SECRET_KEY` is missing from the API environment | Add the correct test or live secret key and restart the API |
| `STRIPE_WEBHOOK_NOT_CONFIGURED` | `STRIPE_WEBHOOK_SECRET` is missing | Copy the signing secret for this exact endpoint into the API environment |
| `INVALID_STRIPE_SIGNATURE` | The endpoint secret does not match the sender, or the body was modified | Use the secret printed by the current Stripe CLI listener locally, or the Dashboard endpoint secret in production |
| `PAYMENT_STORAGE_UNAVAILABLE` | Supabase migration, URL, or server key is unavailable | Apply the entitlement migration and verify `SUPABASE_URL` and `SUPABASE_SECRET_KEY` |
| `STRIPE_ORDER_MISMATCH` | A Dashboard Price ID does not match the server-side AUD amount | Correct the Stripe Price or remove the corresponding `STRIPE_PRICE_*` variable to use inline `price_data` |
| Checkout shows “payment required” | Stripe is intentionally not configured on the API | Configure `STRIPE_SECRET_KEY`; the response is useful for local UI development but does not create a payment |
| Payment succeeds but access remains locked | The webhook was not delivered or entitlement storage failed | Inspect Stripe webhook delivery, API logs, and the Supabase entitlement row; do not unlock access from the redirect alone |

## Production checklist

- Use a live-mode `STRIPE_SECRET_KEY` and a live-mode webhook signing secret together.
- Register the production endpoint at `https://<api-domain>/api/v1/memoir/story/stripe/webhook`.
- Apply `202609250003_story_entitlements.sql` to the production Supabase database.
- Set `MEMORY_SPARK_PUBLIC_URL` to the real public application URL.
- Keep Stripe and Supabase secrets out of the frontend bundle, repository, logs, and client-visible responses.
- Confirm that printed-package shipping countries and fulfillment operations are ready before enabling printed sales.
- Test a complete Checkout-to-webhook flow in Stripe test mode before switching to live mode.

## Reference documentation

- [Stripe Checkout Sessions API](https://docs.stripe.com/api/checkout/sessions/create)
- [Stripe webhooks](https://docs.stripe.com/webhooks)
- [Stripe Checkout fulfillment](https://docs.stripe.com/checkout/fulfillment)
- [Stripe testing](https://docs.stripe.com/testing)
