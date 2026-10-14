#!/bin/sh
set -eu
# Separate from audio installation: never restarts airplay_sonos.service.
# Usage: sh deploy/install-dashboard.sh BRIDGE_LAN_IPV4 [PORT] [SOURCE_ROOT]
[ "$(id -u)" -eq 0 ] || { echo 'Run as root on the bridge' >&2; exit 1; }
bind=${1:?Specify the bridge LAN IPv4 address}
port=${2:-8088}
source_root=${3:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
python3 - "$bind" "$port" <<'PY'
import ipaddress, sys
address = ipaddress.IPv4Address(sys.argv[1])
assert not address.is_unspecified and not address.is_multicast, 'Use a specific local address'
assert 1024 <= int(sys.argv[2]) <= 65535, 'Port must be 1024..65535'
PY
app=/var/airplay_sonos
[ -f "$app/Config.xml" ]
[ -f "$source_root/tools/airconnect_dashboard.py" ]
[ -f "$source_root/deploy/airconnect-dashboard.service" ]
backup=/srv/airconnect-backups/$(date -u +%Y%m%dT%H%M%SZ)-before-dashboard
mkdir -p "$backup" /etc/default
if [ -d "$app/dashboard" ]; then cp -a "$app/dashboard" "$backup/dashboard"; fi
if [ -f /etc/default/airconnect-dashboard ]; then cp -p /etc/default/airconnect-dashboard "$backup/environment"; fi
if [ -f /etc/systemd/system/airconnect-dashboard.service ]; then cp -p /etc/systemd/system/airconnect-dashboard.service "$backup/service"; fi
systemctl is-active airconnect-dashboard.service > "$backup/was-active" 2>/dev/null || true
systemctl is-enabled airconnect-dashboard.service > "$backup/was-enabled" 2>/dev/null || true
cat > "$backup/rollback.sh" <<'ROLLBACK'
#!/bin/sh
set -eu
cd "$(dirname "$0")"
systemctl stop airconnect-dashboard.service || true
systemctl disable airconnect-dashboard.service || true
rm -rf /var/airplay_sonos/dashboard
if [ -d dashboard ]; then cp -a dashboard /var/airplay_sonos/dashboard; fi
rm -f /etc/systemd/system/airconnect-dashboard.service /etc/default/airconnect-dashboard
if [ -f service ]; then cp -p service /etc/systemd/system/airconnect-dashboard.service; fi
if [ -f environment ]; then cp -p environment /etc/default/airconnect-dashboard; fi
systemctl daemon-reload
if [ "$(cat was-enabled)" = enabled ]; then systemctl enable airconnect-dashboard.service; fi
if [ "$(cat was-active)" = active ]; then systemctl start airconnect-dashboard.service; fi
ROLLBACK
chmod 700 "$backup/rollback.sh"
rollback() { code=$?; if [ "$code" -ne 0 ]; then "$backup/rollback.sh"; fi; exit "$code"; }
trap rollback EXIT
stage=$(mktemp -d "$app/.dashboard-XXXXXX")
mkdir -p "$stage/dashboard"
install -m 644 "$source_root/tools/airconnect_dashboard.py" "$stage/airconnect_dashboard.py"
for file in index.html app.js style.css; do
    install -m 644 "$source_root/tools/dashboard/$file" "$stage/dashboard/$file"
done
python3 "$stage/airconnect_dashboard.py" --help >/dev/null
systemctl stop airconnect-dashboard.service 2>/dev/null || true
if [ -d "$app/dashboard" ]; then rm -rf "$app/dashboard"; fi
mv "$stage" "$app/dashboard"
printf 'DASHBOARD_BIND=%s\nDASHBOARD_PORT=%s\n' "$bind" "$port" > /etc/default/airconnect-dashboard
install -m 644 "$source_root/deploy/airconnect-dashboard.service" /etc/systemd/system/airconnect-dashboard.service
systemctl daemon-reload
systemctl enable airconnect-dashboard.service
systemctl start airconnect-dashboard.service
python3 - "$bind" "$port" <<'PY'
import json, time, urllib.request, sys
url = 'http://{}:{}/api/status'.format(sys.argv[1], sys.argv[2])
for attempt in range(10):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            data = json.loads(response.read().decode('utf-8'))
            if response.status != 200 or not data.get('ready') or data.get('collector_error'):
                raise ValueError('Dashboard has not collected a valid snapshot')
        break
    except (OSError, ValueError):
        if attempt == 9: raise
        time.sleep(1)
PY
systemctl is-active --quiet airconnect-dashboard.service
echo "Dashboard: http://$bind:$port"
echo "Rollback: $backup/rollback.sh"
