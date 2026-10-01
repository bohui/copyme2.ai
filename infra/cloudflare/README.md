# CopyMe2 local Apple Container tunnel

Follows the dedicated certificate and macOS launch-agent pattern in
`/Users/bohuihan/trading/scripts/setup-cloudflare-dev-tunnel.sh`.

| Setting | Value |
| --- | --- |
| Hostname | `copyme2.ai` |
| Tunnel | `copyme2-memoir` |
| Tunnel ID | `dff6a4c3-fb6b-4c7b-89b9-f8ccb7733bbb` |
| Origin | `http://127.0.0.1:3010` (Next.js in Apple Container) |
| Generated config | `infra/cloudflare/config.yml` (ignored) |
| Certificate | `~/.cloudflared/copyme2-cert.pem` |
| Tunnel credentials | `~/.cloudflared/dff6a4c3-fb6b-4c7b-89b9-f8ccb7733bbb.json` |
| Launch agent | `~/Library/LaunchAgents/com.cloudflare.cloudflared.copyme2.plist` |

The ingress exposes the frontend and its existing `/api/v1/memoir/*` proxy.
The API, Codex worker, photo worker, Temporal and deterministic worker are not
separately routed through this tunnel. Unmatched hostnames return 404.

## Setup and operation

Set `MEMORY_SPARK_PUBLIC_URL=https://copyme2.ai` in `.env`, then:

```bash
make container-up
make tunnel-plan
make tunnel-setup TUNNEL_ARGS=--replace-existing
make container-health
make tunnel-health
```

The first login opens Cloudflare. Select the `copyme2.ai` zone and authorize
cloudflared. The script verifies its zone ID against the dashboard-verified
CopyMe2 zone before any DNS write. It preserves the existing default certificate,
including on failed login, and stores a separate CopyMe2 certificate. Credentials
must never be committed. `--replace-existing` is needed only for the first
cutover from the existing parking-page CNAME, or another reviewed DNS conflict.
Later `make tunnel-setup` reuses the tunnel and its DNS route.

`MEMORY_SPARK_WEB_PORT` in `.env` controls the origin port; rerun
`make tunnel-start` after a port change. This reinstalls the launch agent using
the existing config without requiring account login or writing DNS.

```bash
make tunnel-status
make tunnel-stop
make tunnel-start
tail -n 50 ~/Library/Logs/com.cloudflare.cloudflared.copyme2.err.log
```

The launch agent starts the connector at this user's login and restarts it after
failure. Start containers with `make container-up` after a reboot. Availability
depends on this Mac remaining awake, online, and logged in.

Supabase Auth must allow `https://copyme2.ai/memoir/start` as an application
redirect URL. Provider callbacks remain Supabase's URLs. See
[`../gcp/google_oauth.md`](../gcp/google_oauth.md). Stripe and Maps credentials
retain their existing configuration; update provider-side webhook/referrer
settings if needed for the public origin.

## Previous route and rollback

Before this cutover, the proxied apex CNAME pointed to
`7e231837-f220-4bcb-85fa-299e8e6af92b.cfargotunnel.com`
(`copyme2-serenity`) and served the domain-sale page. The existing email MX/TXT
records are unchanged by the tunnel script.

To restore that previous route while its old connector is still active:

```bash
cloudflared tunnel --origincert "$HOME/.cloudflared/copyme2-cert.pem" route dns --overwrite-dns 7e231837-f220-4bcb-85fa-299e8e6af92b copyme2.ai
make tunnel-stop
```

## Official reference

[Cloudflare locally managed tunnel setup](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/create-local-tunnel/)
and [configuration and ingress validation](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/configuration-file/).
