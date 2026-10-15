# Generic intercom input

AirConnect-Sonos includes an optional input for live audio from other applications. A sender connects over an authenticated WebSocket, selects a configured room, and supplies PCM audio. The bridge sends that audio to Sonos using the same native UDP transport as native AirPlay output.

This interface can support intercoms, announcements or other live audio sources. It runs independently of AirPlay. Application-specific integrations are outside the scope of this repository.

## Requirements

- A built bridge and intercom worker; see [installation](INSTALL.md).
- A configured real Sonos helper and a separate receiver, both stopped and standalone at setup.
- An approved sender on the trusted LAN with the bearer credential.
- Audio in signed 16-bit little-endian, stereo PCM at 44,100 Hz. Convert other formats before sending.

Setup temporarily uses the helper and releases it before reporting readiness. It commonly took about 5–8 seconds in testing; this is setup time, not measured mouth-to-speaker latency. See [architecture](ARCHITECTURE.md#intercom-input) and [validation](VALIDATION.md) for behavior and limitations.

## Bridge installation

From the checkout on the Linux bridge, after building AirPlay dependencies:

```sh
sh build-intercom.sh
```

For a fresh intercom installation, install the separate worker, Python service, example configuration and systemd unit:

```sh
sudo sh <<'SH'
set -eu
app=/var/airplay_sonos/intercom
test ! -e "$app/config.json"
test ! -e "$app/access.key"
test ! -e /etc/systemd/system/airconnect-intercom.service
install -d -m 700 "$app"
install -m 755 bin/airconnect-intercom-worker "$app/airconnect-intercom-worker"
install -m 755 tools/airconnect_intercom.py "$app/airconnect_intercom.py"
install -m 600 deploy/intercom.example.json "$app/config.json"
install -m 644 deploy/airconnect-intercom.service /etc/systemd/system/airconnect-intercom.service
SH
sudo python3 - <<'PYKEY'
import binascii, os
path = '/var/airplay_sonos/intercom/access.key'
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'wb') as key:
    key.write(binascii.hexlify(os.urandom(32)) + b'\n')
PYKEY
sudoedit /var/airplay_sonos/intercom/config.json
```

The key command refuses to overwrite an existing credential. For upgrades, preserve the key and configuration and follow [component rollback/upgrade guidance](OPERATIONS.md#upgrades-and-rollback).

In the [example configuration](../deploy/intercom.example.json), set `bind` to the bridge LAN IPv4 address, `allowed_clients` to approved sender IPs, and `rooms` to the receivers you want to allow. Use actual device UUIDs without the `uuid:` prefix. Exclude the helper from the receiver list. Set an appropriate `max_volume`; retain the supplied absolute service paths. The room list is explicit and must be updated after name/IP changes.

```sh
sudo python3 -m json.tool /var/airplay_sonos/intercom/config.json >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable airconnect-intercom.service
sudo systemctl start airconnect-intercom.service
sudo systemctl status airconnect-intercom.service --no-pager
```

This does not restart AirPlay. The unit shares the bridge's root-owned native device leases; do not add `PrivateTmp=true`. Include `/var/log/airconnect-intercom.log` in the host's log-rotation policy. Keep configuration and credentials private.

## Input contract

Connect to `ws://BRIDGE_LAN_IP:8089/v1/intercom` with `Authorization: Bearer TOKEN`. The listener also checks the source IP and rejects browser Origin headers. Plain WebSocket does not encrypt audio or credentials; use this on a trusted LAN and do not expose it publicly.

Send a text frame to select a configured room and format. This example requests a muted session:

```json
{"type":"start","room":"Example room","format":"s16le","rate":44100,"channels":2,"volume":0,"muted":true}
```

The service responds with `preparing`, then `ready`, or an `error`. Wait for `ready` before sending binary PCM. Each payload must be a multiple of four bytes and at most 65,536 bytes. Use masked, unfragmented WebSocket messages; compression is unsupported. Send at the audio's real-time rate and keep client-side buffering bounded.

Send WebSocket ping frames during input pauses. Input expires after 15 seconds without traffic/heartbeat, and sessions have a ten-minute limit. Closing the socket stops the worker and attempts verified speaker restoration. At most four sessions are admitted, with helper setup serialized and already-owned receivers refused.

For a first check, use the muted request above, send a short paced stream, close the connection and verify counters and restoration. Only then perform an audible test at a comfortable volume. A clean connection or rising counters do not prove audible playback.

## Monitoring

The read-only dashboard shows current/recent sessions and native device ownership. `GET /v1/status` uses the same bearer header; local status is also available at `/run/airconnect-intercom/status.json`. Inspect errors, received bytes, queue drops, recoveries and worker exit status. See [operations](OPERATIONS.md) for logs and troubleshooting.

The worker uses bounded queues and can recover short scheduling stalls by dropping stale audio. A recovery may produce an audible gap. Longer stalls fail rather than accumulating unlimited audio. Detailed behavior and remaining listening checks are documented in [validation](VALIDATION.md).
