#!/bin/bash

# Configure the CopyMe2 development tunnel with a dedicated zone-scoped
# cloudflared login certificate. Keeping this certificate separate prevents a
# login for another product from changing CopyMe2 DNS.

set -Eeuo pipefail

ZONE="copyme2.ai"
TUNNEL_NAME="copyme2-memoir"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_FILE="$PROJECT_ROOT/infra/cloudflare/config.yml"
ORIGIN_CERT="$HOME/.cloudflared/copyme2-cert.pem"
EXPECTED_ZONE_ID="4b4022337bdca1c33a1f09f21fe74cc8" # Verified in the CopyMe2 Cloudflare dashboard.
LAUNCH_LABEL="com.cloudflare.cloudflared.copyme2"
APPLY=false
FORCE_LOGIN=false
REPLACE_EXISTING=false
INSTALL_SERVICE=true
SERVICE_ONLY=false

usage() {
  cat <<'EOF'
Usage: setup-cloudflare-tunnel.sh [options]

Safely configure the CopyMe2 development Cloudflare Tunnel through a
direct cloudflared browser login. No manually supplied API token is used.

Options:
  --login               Open a fresh Cloudflare login and select copyme2.ai.
  --apply               Create/update the config and DNS routes.
  --replace-existing    Allow cloudflared to overwrite conflicting DNS records.
  --no-service          Do not install/restart the macOS launch agent.
  --service-only        Reinstall the launch agent using the existing config; skip login and DNS.
  --help                Show this help.

The default mode is read-only and prints the intended changes. On the first
apply, the script opens Cloudflare login and asks you to select copyme2.ai.
If you already ran `cloudflared tunnel login`, the default cert.pem is adopted
into the dedicated CopyMe2 certificate only when its zone ID matches copyme2.ai.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --login) FORCE_LOGIN=true ;;
    --apply) APPLY=true ;;
    --replace-existing) REPLACE_EXISTING=true ;;
    --no-service) INSTALL_SERVICE=false ;;
    --service-only) SERVICE_ONLY=true; APPLY=true ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

for command_name in cloudflared jq openssl plutil; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Required command is missing: $command_name" >&2
    exit 1
  fi
done

route_table() {
  cat <<EOF
copyme2.ai|http://127.0.0.1:${MEMORY_SPARK_WEB_PORT:-3010}
EOF
}

validate_hostname() {
  local hostname="$1"
  if [[ "$hostname" != "$ZONE" && "$hostname" != *."$ZONE" ]]; then
    echo "Refusing hostname outside the exact $ZONE zone: $hostname" >&2
    exit 1
  fi
}

while IFS='|' read -r hostname service; do
  validate_hostname "$hostname"
done < <(route_table)

read_cert_zone_id() {
  local cert_file="$1"
  awk '/BEGIN ARGO TUNNEL TOKEN/{inside=1;next}/END ARGO TUNNEL TOKEN/{inside=0}inside' "$cert_file" \
    | tr -d '\n' \
    | openssl base64 -d -A 2>/dev/null \
    | jq -r '.zoneID // empty'
}

verify_cert_zone() {
  local cert_zone_id="$1"
  if [[ "$cert_zone_id" != "$EXPECTED_ZONE_ID" ]]; then
    echo "Certificate is not scoped to $ZONE; refusing DNS changes. Run with --login." >&2
    exit 1
  fi
}

login_if_needed() {
  mkdir -p "$HOME/.cloudflared"

  if [[ "$FORCE_LOGIN" != true ]]; then
    if [[ ! -r "$ORIGIN_CERT" && -r "$HOME/.cloudflared/cert.pem" ]] && [[ "$(read_cert_zone_id "$HOME/.cloudflared/cert.pem")" == "$EXPECTED_ZONE_ID" ]]; then
      install -m 600 "$HOME/.cloudflared/cert.pem" "$ORIGIN_CERT"
    fi
  fi

  if [[ "$FORCE_LOGIN" == true || ! -r "$ORIGIN_CERT" ]]; then
    echo "Opening Cloudflare login. Select the $ZONE website in the browser."
    # cloudflared login always writes ~/.cloudflared/cert.pem, even when the
    # global --origincert flag is supplied. Stage that fixed path so another
    # product's certificate is restored whether login succeeds or fails.
    local default_cert="$HOME/.cloudflared/cert.pem"
    local login_tmp
    local had_default=false
    local had_origin=false
    local login_succeeded=false
    login_tmp="$(mktemp -d "${TMPDIR:-/tmp}/copyme2-login.XXXXXX")"

    if [[ -e "$default_cert" ]]; then
      mv "$default_cert" "$login_tmp/default-cert.pem"
      had_default=true
    fi
    if [[ -e "$ORIGIN_CERT" ]]; then
      mv "$ORIGIN_CERT" "$login_tmp/copyme2-cert.pem"
      had_origin=true
    fi

    restore_login_files() {
      if [[ "$login_succeeded" == true && -e "$default_cert" ]]; then
        mv "$default_cert" "$ORIGIN_CERT"
        chmod 600 "$ORIGIN_CERT"
      else
        if [[ -e "$default_cert" ]]; then
          mv "$default_cert" "$login_tmp/incomplete-cert.pem"
        fi
        if [[ "$had_origin" == true && -e "$login_tmp/copyme2-cert.pem" ]]; then
          mv "$login_tmp/copyme2-cert.pem" "$ORIGIN_CERT"
        fi
      fi
      if [[ "$had_default" == true && -e "$login_tmp/default-cert.pem" ]]; then
        mv "$login_tmp/default-cert.pem" "$default_cert"
      fi
      rm -rf "$login_tmp"
    }

    trap restore_login_files EXIT INT TERM
    cloudflared tunnel login
    if [[ ! -r "$default_cert" ]]; then
      echo "Cloudflare login did not download $default_cert." >&2
      exit 1
    fi
    login_succeeded=true
    restore_login_files
    trap - EXIT INT TERM
  fi

  if [[ ! -r "$ORIGIN_CERT" ]]; then
    echo "Cloudflare did not write the dedicated certificate: $ORIGIN_CERT" >&2
    exit 1
  fi

  local cert_zone_id
  cert_zone_id="$(read_cert_zone_id "$ORIGIN_CERT")"
  if [[ -z "$cert_zone_id" ]]; then
    echo "Unable to read the zone ID from $ORIGIN_CERT." >&2
    exit 1
  fi
  verify_cert_zone "$cert_zone_id"
}

echo "CopyMe2 development tunnel plan"
echo "  Zone:        $ZONE"
echo "  Tunnel:      $TUNNEL_NAME"
echo "  Login cert:  $ORIGIN_CERT"
echo "  Config:      $CONFIG_FILE"
echo "  DNS method:  cloudflared with a dedicated direct-login certificate"
echo "  Routes:"
while IFS='|' read -r hostname service; do
  printf '    %-24s -> %s\n' "$hostname" "$service"
done < <(route_table)

if [[ "$APPLY" != true && "$FORCE_LOGIN" != true ]]; then
  echo
  echo "Plan only; nothing changed. Re-run with --apply to log in and configure the tunnel."
  exit 0
fi

if [[ "$SERVICE_ONLY" != true ]]; then
  login_if_needed
fi

if [[ "$APPLY" != true ]]; then
  echo "Dedicated $ZONE login saved and confirmed. No tunnel or DNS changes were requested."
  exit 0
fi

if [[ "$SERVICE_ONLY" == true ]]; then
  test -r "$CONFIG_FILE" || { echo "Missing $CONFIG_FILE; run --apply first." >&2; exit 1; }
  tunnel_id="$(awk '/^tunnel:/{print $2}' "$CONFIG_FILE")"
else
tunnel_json="$(cloudflared tunnel --origincert "$ORIGIN_CERT" list --output json)"
tunnel_count="$(jq --arg name "$TUNNEL_NAME" '[.[] | objects | select(.name == $name and (.deleted_at == null or .deleted_at == "0001-01-01T00:00:00Z"))] | length' <<<"$tunnel_json")"
if [[ "$tunnel_count" -gt 1 ]]; then
  echo "Multiple active tunnels have the exact name $TUNNEL_NAME; refusing to guess." >&2
  exit 1
fi

tunnel_id=""
if [[ "$tunnel_count" -eq 1 ]]; then
  tunnel_id="$(jq -r --arg name "$TUNNEL_NAME" '.[] | objects | select(.name == $name and (.deleted_at == null or .deleted_at == "0001-01-01T00:00:00Z")) | .id' <<<"$tunnel_json")"
else
  echo "Creating tunnel $TUNNEL_NAME..."
  created_tunnel="$(cloudflared tunnel --origincert "$ORIGIN_CERT" create --output json "$TUNNEL_NAME")"
  tunnel_id="$(jq -r '.id // empty' <<<"$created_tunnel")"
  unset created_tunnel
fi

fi

if [[ ! "$tunnel_id" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
  echo "cloudflared did not return a tunnel ID." >&2
  exit 1
fi

credentials_file="$HOME/.cloudflared/$tunnel_id.json"
if [[ ! -r "$credentials_file" ]]; then
  echo "Missing tunnel credentials: $credentials_file" >&2
  exit 1
fi

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/copyme2-cloudflare.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT
generated_config="$tmp_dir/cloudflare-tunnel.yml"
{
  printf 'tunnel: %s\n' "$tunnel_id"
  printf 'credentials-file: %s\n\n' "$credentials_file"
  printf 'ingress:\n'
  while IFS='|' read -r hostname service; do
    printf '  - hostname: %s\n' "$hostname"
    printf '    service: %s\n' "$service"
  done < <(route_table)
  printf '  - service: http_status:404\n'
} >"$generated_config"

cloudflared tunnel --config "$generated_config" ingress validate
mkdir -p "$(dirname "$CONFIG_FILE")"
install -m 600 "$generated_config" "$CONFIG_FILE"

if [[ "$SERVICE_ONLY" != true ]]; then
while IFS='|' read -r hostname service; do
  route_args=(tunnel --origincert "$ORIGIN_CERT" --config "$CONFIG_FILE" route dns)
  if [[ "$REPLACE_EXISTING" == true ]]; then
    route_args+=(--overwrite-dns)
  fi
  route_args+=("$TUNNEL_NAME" "$hostname")

  route_output="$(cloudflared "${route_args[@]}" 2>&1)" || {
    echo "$route_output" >&2
    echo "Failed to route $hostname. Use --replace-existing only after reviewing a conflict." >&2
    exit 1
  }
  echo "$route_output"

  created_hostname="$(sed -n 's/.*Added CNAME \([^ ]*\) .*/\1/p' <<<"$route_output" | tail -n 1)"
  if [[ -n "$created_hostname" && "$created_hostname" != "$hostname" ]]; then
    echo "Cloudflare reported unexpected hostname $created_hostname; stop and inspect DNS immediately." >&2
    exit 1
  fi
done < <(route_table)

fi

if [[ "$INSTALL_SERVICE" == true ]]; then
  launch_agents_dir="$HOME/Library/LaunchAgents"
  launch_agent="$launch_agents_dir/$LAUNCH_LABEL.plist"
  mkdir -p "$launch_agents_dir" "$HOME/Library/Logs"
  generated_plist="$tmp_dir/$LAUNCH_LABEL.plist"
  cat >"$generated_plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LAUNCH_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(command -v cloudflared)</string>
    <string>tunnel</string><string>--config</string><string>$CONFIG_FILE</string>
    <string>run</string><string>$tunnel_id</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/$LAUNCH_LABEL.out.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/$LAUNCH_LABEL.err.log</string>
</dict>
</plist>
EOF
  plutil -lint "$generated_plist" >/dev/null
  install -m 600 "$generated_plist" "$launch_agent"
  user_domain="gui/$(id -u)"
  launchctl bootout "$user_domain/$LAUNCH_LABEL" >/dev/null 2>&1 || true
  # launchd may briefly retain the old job after bootout. Wait for that state
  # transition so bootstrap does not fail with a misleading I/O error.
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if ! launchctl print "$user_domain/$LAUNCH_LABEL" >/dev/null 2>&1; then
      break
    fi
    sleep 0.2
  done
  launchctl enable "$user_domain/$LAUNCH_LABEL"
  if ! launchctl bootstrap "$user_domain" "$launch_agent"; then
    # Treat an already-loaded healthy job as success; otherwise surface the
    # bootstrap failure instead of hiding it.
    launchctl print "$user_domain/$LAUNCH_LABEL" >/dev/null 2>&1 || exit 1
  fi
fi

echo "CopyMe2 development tunnel configured successfully."
echo "Start the Apple Container stack with: make container-up"
echo "Public origin: https://copyme2.ai"
