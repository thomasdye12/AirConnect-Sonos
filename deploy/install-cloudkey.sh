#!/bin/sh
set -eu
# Run on the CloudKey after sh build-cloudkey.sh. No SSH credentials are stored.
# Optional argument: checkout/build root. Service paths follow deploy/airplay_sonos.service.
[ "$(id -u)" -eq 0 ] || { echo 'Run as root on the CloudKey' >&2; exit 1; }
build=${1:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
[ -x "$build/bin/airupnp-linux-arm" ]
[ -f "$build/tools/airconnectctl.py" ]
app=/var/airplay_sonos
backup=/srv/airconnect-backups/$(date -u +%Y%m%dT%H%M%SZ)-before-upgrade
mkdir -p "$backup"
cp -p "$app/airupnp-linux-arm" "$backup/airupnp-linux-arm"
cp -p "$app/Config.xml" "$backup/Config.xml"
cp -p /etc/systemd/system/airplay_sonos.service "$backup/airplay_sonos.service"
if [ -f "$app/airconnectctl.py" ]; then cp -p "$app/airconnectctl.py" "$backup/airconnectctl.py"; fi
cat > "$backup/rollback.sh" <<'ROLLBACK'
#!/bin/sh
set -eu
cd "$(dirname "$0")"
systemctl stop airplay_sonos.service
cp -p airupnp-linux-arm /var/airplay_sonos/airupnp-linux-arm.rollback
mv /var/airplay_sonos/airupnp-linux-arm.rollback /var/airplay_sonos/airupnp-linux-arm
cp -p Config.xml /var/airplay_sonos/Config.xml
if [ -f airconnectctl.py ]; then cp -p airconnectctl.py /var/airplay_sonos/airconnectctl.py; else rm -f /var/airplay_sonos/airconnectctl.py; fi
systemctl start airplay_sonos.service
ROLLBACK
chmod 700 "$backup/rollback.sh"
rollback() { code=$?; if [ "$code" -ne 0 ]; then "$backup/rollback.sh"; fi; exit "$code"; }
trap rollback EXIT
install -m 755 "$build/bin/airupnp-linux-arm" "$app/airupnp-linux-arm.new"
install -m 755 "$build/tools/airconnectctl.py" "$app/airconnectctl.py"
python3 - <<'PY'
import xml.etree.ElementTree as E
p='/var/airplay_sonos/Config.xml'
t=E.parse(p);r=t.getroot();e=r.find('sonos_cache')
if e is None:e=E.SubElement(r,'sonos_cache')
e.text='/var/airplay_sonos/rooms-cache.json'
t.write(p+'.new',encoding='UTF-8',xml_declaration=True)
PY
systemctl stop airplay_sonos.service
mv "$app/airupnp-linux-arm.new" "$app/airupnp-linux-arm"
mv "$app/Config.xml.new" "$app/Config.xml"
systemctl start airplay_sonos.service
systemctl is-active airplay_sonos.service
python3 "$app/airconnectctl.py" status
printf 'Rollback backup: %s\n' "$backup"
