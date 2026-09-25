#!/usr/bin/env python3
"""Create or reuse CopyMe2 Memoir products and one-time Stripe prices.

The catalog is imported from ``apps.api.story_payments`` so the generated
Stripe Price IDs always match the amounts enforced by the API. The script uses
Stripe's REST API through the repository's existing ``httpx`` dependency; no
Stripe SDK installation is required.

Examples:

    python3 infra/stripe/setup_stripe.py --mode test --dry-run
    python3 infra/stripe/setup_stripe.py --mode test --yes
    python3 infra/stripe/setup_stripe.py --mode test --auth cli --yes
    python3 infra/stripe/setup_stripe.py --mode live --yes \
        --webhook-url https://api.example.com/api/v1/memoir/story/stripe/webhook
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.api.story_payments import (  # noqa: E402
    ADDITIONAL_BOOK_AMOUNT_MINOR,
    STORY_CURRENCY,
    STORY_PLANS,
)


STRIPE_API_BASE = "https://api.stripe.com/v1"
WEBHOOK_EVENTS = (
    "checkout.session.completed",
    "checkout.session.async_payment_succeeded",
)
PRICE_ENV_KEYS = {
    "electronic_memoir_v1": "STRIPE_PRICE_ELECTRONIC",
    "printed_memoir_v1": "STRIPE_PRICE_PRINTED",
    "family_memoir_v1": "STRIPE_PRICE_FAMILY",
    "additional_book": "STRIPE_PRICE_ADDITIONAL_BOOK",
}


class StripeSetupError(RuntimeError):
    """Raised when Stripe setup cannot complete safely."""


def _money(amount_minor: int) -> str:
    return f"{amount_minor / 100:.2f} {STORY_CURRENCY}"


def _product_definitions() -> list[dict[str, Any]]:
    definitions = []
    for plan_key, plan in STORY_PLANS.items():
        definitions.append(
            {
                "plan_key": plan_key,
                "env_key": PRICE_ENV_KEYS[plan_key],
                "name": plan["name"],
                "description": plan["description"],
                "amount_minor": plan["price_minor"],
                "metadata": {
                    "plan_key": plan_key,
                    "product": "memoir",
                    "billing": "one_time",
                },
            }
        )

    definitions.append(
        {
            "plan_key": "additional_book",
            "env_key": PRICE_ENV_KEYS["additional_book"],
            "name": "Additional printed book",
            "description": "One additional copy of the printed memoir.",
            "amount_minor": ADDITIONAL_BOOK_AMOUNT_MINOR,
            "metadata": {
                "plan_key": "additional_book",
                "product": "memoir",
                "billing": "one_time",
            },
        }
    )
    return definitions


class StripeClient:
    """Small Stripe REST client for the setup operations used here."""

    def __init__(self, api_key: str):
        self.http = httpx.Client(
            auth=(api_key, ""),
            headers={"User-Agent": "copyme2-memoir-stripe-setup/1.0"},
            timeout=30,
        )

    def close(self) -> None:
        self.http.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        data: Iterable[tuple[str, str]] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            encoded_data = urlencode(list(data)) if data is not None else None
            response = self.http.request(
                method,
                f"{STRIPE_API_BASE}{path}",
                content=encoded_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"} if encoded_data is not None else None,
                params=params,
            )
        except httpx.HTTPError as error:
            raise StripeSetupError(f"Stripe request failed: {error}") from error

        if response.is_error:
            try:
                error_payload = response.json().get("error", {})
                message = error_payload.get("message") or response.text
            except (ValueError, AttributeError):
                message = response.text
            raise StripeSetupError(f"Stripe returned HTTP {response.status_code}: {message}")

        try:
            return response.json()
        except ValueError as error:
            raise StripeSetupError("Stripe returned a non-JSON response.") from error

    def list_all(self, path: str, *, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
        query = {"limit": "100", **(params or {})}
        results: list[dict[str, Any]] = []
        while True:
            payload = self.request("GET", path, params=query)
            page = payload.get("data") or []
            results.extend(page)
            if not payload.get("has_more") or not page:
                return results
            query["starting_after"] = str(page[-1]["id"])


class StripeCLIClient:
    """Stripe REST adapter that delegates authentication to ``stripe login``."""

    def __init__(self, mode: str):
        self.binary = shutil.which("stripe")
        if not self.binary:
            raise StripeSetupError("Stripe CLI is not installed. Install it, then run `make stripe_login`.")
        self.mode = mode

    def close(self) -> None:
        return None

    def request(
        self,
        method: str,
        path: str,
        *,
        data: Iterable[tuple[str, str]] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        parts = [part for part in path.strip("/").split("/") if part]
        if parts and parts[0] == "v1":
            parts = parts[1:]
        if not parts or len(parts) > 2:
            raise StripeSetupError(f"Stripe CLI adapter cannot address {path}.")

        resource = parts[0]
        identifier = parts[1] if len(parts) == 2 else None
        if method == "GET":
            operation = "retrieve" if identifier else "list"
        elif method == "POST":
            operation = "update" if identifier else "create"
        else:
            raise StripeSetupError(f"Stripe CLI adapter does not support {method} {path}.")

        command = [self.binary, "--color", "off", resource, operation, "--confirm"]
        if self.mode == "live":
            command.append("--live")
        if identifier:
            command.append(identifier)
        for key, value in (params or {}).items():
            command.extend(["-d", f"{key}={value}"])
        for key, value in data or ():
            command.extend(["-d", f"{key}={value}"])

        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise StripeSetupError(f"Stripe CLI request failed: {detail}")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise StripeSetupError("Stripe CLI returned a non-JSON response.") from error

    def list_all(self, path: str, *, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
        query = {"limit": "100", **(params or {})}
        results: list[dict[str, Any]] = []
        while True:
            payload = self.request("GET", path, params=query)
            page = payload.get("data") or []
            results.extend(page)
            if not payload.get("has_more") or not page:
                return results
            query["starting_after"] = str(page[-1]["id"])


def _metadata_data(metadata: dict[str, str]) -> list[tuple[str, str]]:
    return [(f"metadata[{key}]", value) for key, value in metadata.items()]


def ensure_product(client: StripeClient, definition: dict[str, Any]) -> tuple[str, bool]:
    products = client.list_all("/products", params={"active": "true"})
    for product in products:
        if (product.get("metadata") or {}).get("plan_key") == definition["plan_key"]:
            print(f"  Reusing product {product['id']}: {definition['name']}")
            return str(product["id"]), True

    data = [
        ("name", definition["name"]),
        ("description", definition["description"]),
        *_metadata_data(definition["metadata"]),
    ]
    product = client.request("POST", "/products", data=data)
    print(f"  Created product {product['id']}: {definition['name']}")
    return str(product["id"]), False


def ensure_price(
    client: StripeClient,
    definition: dict[str, Any],
    product_id: str,
) -> tuple[str, bool]:
    prices = client.list_all(
        "/prices",
        params={
            "active": "true",
            "product": product_id,
            "type": "one_time",
            "currency": STORY_CURRENCY.lower(),
        },
    )
    for price in prices:
        if (
            price.get("unit_amount") == definition["amount_minor"]
            and str(price.get("currency", "")).lower() == STORY_CURRENCY.lower()
            and not price.get("recurring")
        ):
            print(f"    Reusing price {price['id']}: {_money(definition['amount_minor'])}")
            return str(price["id"]), True

    data = [
        ("product", product_id),
        ("currency", STORY_CURRENCY.lower()),
        ("unit_amount", str(definition["amount_minor"])),
        *_metadata_data(definition["metadata"]),
    ]
    price = client.request("POST", "/prices", data=data)
    print(f"    Created price {price['id']}: {_money(definition['amount_minor'])}")
    return str(price["id"]), False


def find_webhook(client: StripeClient, url: str) -> dict[str, Any] | None:
    for endpoint in client.list_all("/webhook_endpoints"):
        if endpoint.get("url") == url:
            return endpoint
    return None


def ensure_webhook(client: StripeClient, url: str, description: str) -> str | None:
    existing = find_webhook(client, url)
    enabled_events = [("enabled_events[]", event) for event in WEBHOOK_EVENTS]
    if existing:
        client.request(
            "POST",
            f"/webhook_endpoints/{existing['id']}",
            data=[("description", description), *enabled_events],
        )
        print(f"  Reused and synchronized webhook {existing['id']}: {url}")
        print("  Stripe does not return an existing endpoint secret; keep the current STRIPE_WEBHOOK_SECRET.")
        return os.getenv("STRIPE_WEBHOOK_SECRET", "").strip() or None

    endpoint = client.request(
        "POST",
        "/webhook_endpoints",
        data=[
            ("url", url),
            ("description", description),
            *enabled_events,
        ],
    )
    print(f"  Created webhook {endpoint['id']}: {url}")
    return str(endpoint.get("secret") or "") or None


def write_env_config(
    path: Path,
    price_ids: dict[str, str],
    webhook_secret: str | None,
    webhook_url: str | None,
    api_key: str | None,
    mode: str,
) -> None:
    lines = [
        f"# Generated by infra/stripe/setup_stripe.py ({mode} mode).",
        "# Copy these values into the API environment; do not commit this file.",
        "",
    ]
    if api_key:
        lines.append(f"STRIPE_SECRET_KEY={api_key}")
    else:
        lines.append("# STRIPE_SECRET_KEY=sk_test_... or sk_live_... (required by the API runtime)")
    lines.append("")
    for definition in _product_definitions():
        lines.append(f"{definition['env_key']}={price_ids[definition['env_key']]}")
    if webhook_url:
        lines.extend(["", f"STRIPE_WEBHOOK_URL={webhook_url}"])
    if webhook_secret:
        lines.extend(["", f"STRIPE_WEBHOOK_SECRET={webhook_secret}"])
    else:
        lines.extend(
            [
                "",
                "# If an existing webhook was reused, set this from Stripe Dashboard or the current API environment:",
                "# STRIPE_WEBHOOK_SECRET=whsec_...",
            ]
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)
    print(f"\nWrote environment config: {path}")


def print_catalog() -> None:
    print(f"Catalog ({STORY_CURRENCY}, one-time prices):")
    for definition in _product_definitions():
        print(f"  - {definition['name']}: {_money(definition['amount_minor'])} -> {definition['env_key']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("test", "live"),
        default="test",
        help="Stripe account mode to configure (default: test).",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("STRIPE_SECRET_KEY", "").strip(),
        help="Stripe secret key; defaults to STRIPE_SECRET_KEY.",
    )
    parser.add_argument(
        "--auth",
        choices=("api-key", "cli"),
        default="api-key",
        help="Stripe authentication backend (default: api-key; cli uses `stripe login`).",
    )
    parser.add_argument(
        "--webhook-url",
        help="Optional public webhook URL to create or synchronize.",
    )
    parser.add_argument(
        "--webhook-description",
        default="CopyMe2 Memoir webhook",
        help="Description for a created webhook endpoint.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Generated env config path (default: infra/stripe/stripe_env_config_<mode>.txt).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the catalog and planned webhook without calling Stripe or writing files.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.webhook_url and not args.webhook_url.startswith("https://"):
        raise StripeSetupError("--webhook-url must use HTTPS; use Stripe CLI forwarding for local development.")

    if args.dry_run:
        return

    if args.auth == "cli":
        if not shutil.which("stripe"):
            raise StripeSetupError("Stripe CLI is not installed. Install it, then run `make stripe_login`.")
        return

    if not args.api_key:
        raise StripeSetupError("Set STRIPE_SECRET_KEY or pass --api-key.")
    expected_prefix = "sk_test_" if args.mode == "test" else "sk_live_"
    if not args.api_key.startswith(expected_prefix):
        raise StripeSetupError(f"--mode {args.mode} requires a key beginning with {expected_prefix}.")


def main() -> int:
    args = parse_args()
    try:
        validate_args(args)
        print_catalog()
        if args.webhook_url:
            print(f"Webhook: {args.webhook_url}")
            print(f"Events: {', '.join(WEBHOOK_EVENTS)}")

        if args.dry_run:
            print("\nDry run complete; no Stripe resources or files were changed.")
            return 0

        if not args.yes:
            answer = input("\nCreate or reuse these Stripe resources? [y/N] ").strip().lower()
            if answer not in {"y", "yes"}:
                print("Cancelled.")
                return 0

        client: StripeClient | StripeCLIClient
        client = StripeCLIClient(args.mode) if args.auth == "cli" else StripeClient(args.api_key)
        try:
            price_ids: dict[str, str] = {}
            print(f"\nConfiguring Stripe in {args.mode} mode...")
            for definition in _product_definitions():
                product_id, _ = ensure_product(client, definition)
                price_id, _ = ensure_price(client, definition, product_id)
                price_ids[definition["env_key"]] = price_id

            webhook_secret = None
            if args.webhook_url:
                webhook_secret = ensure_webhook(client, args.webhook_url, args.webhook_description)
        finally:
            client.close()

        output_path = args.output or PROJECT_ROOT / "infra" / "stripe" / f"stripe_env_config_{args.mode}.txt"
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path
        write_env_config(
            output_path,
            price_ids,
            webhook_secret,
            args.webhook_url,
            args.api_key if args.auth == "api-key" else None,
            args.mode,
        )
        print("\nSetup complete. Review the generated file and copy its values into the API environment.")
        if args.webhook_url and not webhook_secret:
            print("The webhook endpoint already existed, so retrieve its existing signing secret from Stripe Dashboard.")
        return 0
    except (StripeSetupError, KeyboardInterrupt) as error:
        print(f"\nSetup failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
