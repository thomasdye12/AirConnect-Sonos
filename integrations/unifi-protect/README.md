# Native Sonos intercom input

The Protect talkback service can mirror microphone audio to the existing native Sonos sender. The camera's original WebSocket forwarding stays in place. The new path is:

`AAC microphone frames → Protect / FFmpeg → authenticated PCM WebSocket → C worker → Sonos UDP`

This does not use AirPlay or the Sonos HTTP radio audio-fetch path. A real, stopped, standalone Sonos helper is still required to prepare each session. The chosen receiver must also be stopped and standalone. AirPlay and intercom workers use the same per-device flock leases; an occupied receiver cannot be taken over. Intercom admission allows four sessions, with helper setup serialized by its lease.

## Wire contract

Connect to `ws://BRIDGE_LAN_IP:8089/v1/intercom` with an `Authorization: Bearer TOKEN` header. The service also checks the source IP against `allowed_clients` and rejects browser Origin headers. This is a trusted-LAN service; plain WebSocket does not encrypt audio or the credential. Do not expose it publicly. A TLS reverse proxy would need an explicit deployment/configuration change.

Send this JSON text frame first:

```json
{"type":"start","room":"Example room","format":"s16le","rate":44100,"channels":2,"volume":35,"muted":false}
```

`room` accepts a configured UUID or a case-insensitive room name. The response is `preparing`, followed by `ready` after the receiver has been promoted and the helper restored/released, or `error` if setup fails. **Do not send microphone PCM until ready.** Preparation commonly took about 5–8 seconds in the recorded deployment; this is setup time, not measured mouth-to-speaker latency. Open the intercom before beginning to talk.

Once ready, send binary frames containing raw, signed 16-bit little-endian, stereo PCM at 44,100 Hz. Payloads must be multiples of four bytes, at most 64 KiB each. The bundled adapter uses 8 KiB or smaller frames. Compression and fragmented WebSocket messages are not supported. Send ping frames during microphone pauses; the adapter sends one every three seconds. Input expires after 15 seconds without traffic/heartbeat; sessions also have a ten-minute limit. Closing the WebSocket stops the worker and attempts verified speaker restoration.

The worker primes 60 ms of PCM and caps its queue at 200 ms. It sends silence during setup/underruns, counts discarded old frames on overflow, and retains a 75 ms UDP scheduling lead. These values are not an acoustic latency guarantee. The adapter stops on excessive network/decoder backpressure rather than queueing unlimited speech. This path does not apply AirPlay's per-room video synchronization offset.

The intercom worker can recover a scheduling delay between 250 and 500 ms by rebasing future packet deadlines and discarding its queued stale PCM. Packet sequence and sample positions remain continuous; expired packets are not burst to the receiver. Recovery is opt-in for intercom; the AirPlay sender retains strict pacing. The bridge allows up to 750 ms of pipe backpressure, then closes a persistently stalled session. A recovery can produce a short audible gap. Status includes a `recoveries` counter, and native sender errors retain their cause instead of being overwritten by a secondary congestion error.

`GET /v1/status` uses the same Authorization header. The read-only dashboard reads `/run/airconnect-intercom/status.json` locally, shows current and recent intercom counters, and includes workers' actual device leases in native ownership. It never receives the intercom token.

## Bridge installation

First complete the [bridge build and helper configuration](../../docs/INSTALL.md). Run the following from the checkout on the Linux bridge. The installer block is for a **fresh intercom installation** and refuses an existing config, key or service unit:

```sh
sh build-intercom.sh
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

The key command creates a random 64-character secret without printing it and refuses to overwrite an existing key. Keep it private. For an upgrade, preserve that key/config and use [the component upgrade procedure](../../docs/OPERATIONS.md#upgrades-and-rollback).

In the [example JSON](../../deploy/intercom.example.json), replace:

- `bind`: the bridge's LAN IPv4 address; `port` defaults to 8089.
- `allowed_clients`: the actual source IP of the Protect host or other approved sender.
- `rooms`: explicit names, addresses and UUIDs of receivers you want to allow. UUIDs are `RINCON_...` without the `uuid:` prefix. Use the real device identity, not an invented UUID. Do not include the helper as a receiver.
- `max_volume`: your chosen ceiling; the example permits 100. The adapter's starting request is 35, which must fit that ceiling.

Get room identities using the controller's `rooms` output, the API `/zones` response or the speaker description at `http://SPEAKER_IP:1400/xml/device_description.xml`. This room list is explicit, not automatically discovered: update it after name/IP changes. The existing `native-helper.json` remains authoritative for helper identity. Keep the configured absolute worker, token, helper and status paths when using the supplied unit.

```sh
sudo python3 -m json.tool /var/airplay_sonos/intercom/config.json >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable airconnect-intercom.service
sudo systemctl start airconnect-intercom.service
sudo systemctl status airconnect-intercom.service --no-pager
sudo tail -n 60 /var/log/airconnect-intercom.log
```

This separately built worker does not replace or restart AirPlay. The supplied unit runs as root to share the bridge's root-owned device leases. It creates the runtime status directory and permits graceful restoration on shutdown. Do not add `PrivateTmp=true`: native AirPlay and intercom must see the same lease directory. The intercom log is `/var/log/airconnect-intercom.log`; include it in log rotation. The Python service uses the standard library and has been run on Python 3.4. Linux service installation is not provided for macOS; Apple Silicon worker builds use `HOST=macos PLATFORM=arm64 CC=clang sh build-intercom.sh` after building the bridge dependencies.

Intercom does not require an active AirPlay connection or AirPlay native mode, but always requires the configured real helper. If using HTTP AirPlay, reserve that helper yourself; native-mode helper exclusion does not protect it from unrelated controllers.

Sonos can acknowledge a group change before its topology updates. Setup polls after promotion and again after the recovery detach (up to three seconds per polling phase). Each speaker must report its own group as standalone, with its expected coordinator identity, address and single member. The helper's cached view of the receiver can retain an orphaned old group and is not authoritative for receiver membership. Microphone audio is accepted only after both local membership checks and helper restoration succeed. A speaker that remains grouped still causes bounded failure and restoration. Native failures identify the setup stage in the log, WebSocket error and dashboard session status; snapshot logs distinguish an active transport from a missing standalone identity.

## Protect adapter

Copy `airconnect-intercom.js` beside the existing `protect-talkback.js`; it uses that project's installed `ws` dependency and FFmpeg executable. The accompanying `protect-talkback.patch` records the integration against the inspected service. The adapter is an ES module and was tested with Node 18 and FFmpeg 5.1.2. From your Protect checkout, check before applying (replace the path):

```sh
git status --short
git apply --unidiff-zero --check /absolute/path/AirConnect-Sonos/integrations/unifi-protect/protect-talkback.patch
# After reviewing the patch and backing up the current module:
git apply --unidiff-zero /absolute/path/AirConnect-Sonos/integrations/unifi-protect/protect-talkback.patch
```

Copy the adapter and its two test files into the same directory as `protect-talkback.js`. If the patch check fails, adapt the changes to your version; do not force it. The existing project must provide `ws` and a working FFmpeg executable. No full copy of the private Protect project is included.

Create an ignored `airconnect-intercom.local.json` beside the adapter:

```json
{
  "enabled": true,
  "url": "ws://BRIDGE_LAN_IP:8089/v1/intercom",
  "tokenFile": "/absolute/private/path/intercom.key",
  "ffmpeg": "/usr/local/bin/ffmpeg",
  "volume": 35
}
```

Copy the bridge credential securely into that private key file without pasting it into source or logs. Protect both files with mode 0600. Add `/airconnect-intercom.local.json` and `/airconnect-intercom.local.key` to the Protect project's `.gitignore` (adjust paths if the adapter is in a subdirectory), and keep any differently named key outside the checkout. Verify with `git check-ignore` before committing. Example, for a key beside the adapter:

```sh
chmod 600 airconnect-intercom.local.json airconnect-intercom.local.key
git check-ignore airconnect-intercom.local.json airconnect-intercom.local.key
```

Set `tokenFile` to that key's absolute path. On Linux, FFmpeg is often `/usr/bin/ffmpeg`; use `command -v ffmpeg` to check. `SONOS_NATIVE_CONFIG` can point to another config path. Restart the Protect service to load changes. The existing client URL and `sonosSpeaker` query parameter remain unchanged; the ready response gains `transport: "native-udp"`.

With native mode enabled, Sonos audio bypasses the HTTP `urlradio` session, its volume controls and resume polling. The native worker owns volume/restoration. No automatic fallback happens after an error, to prevent two competing backends. For rollback, set `enabled` to false and restart Protect; the original HTTP path remains in the module. Back up the current module before patching it.

For app connection failures, filter Protect's stdout/stderr for `[protect-talkback]`. Timestamped events distinguish the client connection, camera endpoint lookup, bridge connection, speaker readiness, first microphone bytes, first decoded PCM and closure. Closing counters include accepted AAC bytes, PCM bytes and bytes discarded before speaker readiness; no audio payload or connection credential is logged. Runtime bridge errors are sent as an error message before closing the client socket. A client that disconnects during camera endpoint lookup no longer starts speaker preparation afterwards.

## First connection test

On the approved Protect host, run this from the directory with the adapter config and `ws` installed. Replace `Example room` with a configured receiver. Stop and ungroup both receiver and helper first. This is a **muted ten-second PCM test** that temporarily controls the receiver; it is not a listening test and bypasses AAC/FFmpeg and the camera path.

```sh
node --input-type=module <<'JS'
import WebSocket from 'ws';
import { readFileSync } from 'node:fs';
const config = JSON.parse(readFileSync('./airconnect-intercom.local.json', 'utf8'));
const token = readFileSync(config.tokenFile, 'utf8').trim();
const ws = new WebSocket(config.url, {
  headers: { Authorization: `Bearer ${token}` }, perMessageDeflate: false
});
let timer, end, ready = false, finished = false;
const fail = message => {
  console.error(message); process.exitCode = 1;
  clearInterval(timer); ws.close();
};
const deadline = setTimeout(() => {
  fail('Test deadline exceeded'); ws.terminate();
}, 60000);
ws.on('open', () => ws.send(JSON.stringify({type: 'start', room: 'Example room',
  format: 's16le', rate: 44100, channels: 2, volume: 0, muted: true})));
ws.on('message', data => {
  let message;
  try { message = JSON.parse(data.toString()); }
  catch { return fail('Invalid bridge response'); }
  console.log(message);
  if (message.type === 'error') return fail(message.message);
  if (message.type === 'ready' && !ready) {
    ready = true;
    timer = setInterval(() => {
      if (ws.bufferedAmount > 35280) return fail('Sender backpressure');
      ws.send(Buffer.alloc(3528)); // 20 ms, stereo 44.1 kHz s16le silence
    }, 20);
    end = setTimeout(() => { finished = true; clearInterval(timer); ws.close(); }, 10000);
  }
});
ws.on('error', error => fail(error.message));
ws.on('close', code => {
  clearTimeout(deadline); clearTimeout(end); clearInterval(timer);
  if (!finished) process.exitCode = 1;
  console.log('Socket closed:', code, 'Check bridge restoration and counters.');
});
JS
```

On the bridge, inspect the dashboard or `sudo python3 -m json.tool /run/airconnect-intercom/status.json` after cleanup. Expect readiness, increasing received bytes, a clean worker exit and verified receiver/helper restoration in the log. A clean client close alone does not verify cleanup. Then test the app with an audible microphone session at a comfortable volume, allowing preparation to finish before speaking. Check both the camera and Sonos output. Report the exact error and whether you deliberately ended the session if it stops.

## Verification

- `python3 -m unittest discover -s tests -p test_intercom.py`: masked PCM/control framing, malformed/unmasked/oversized rejection, authentication, Origin rejection, format/volume/room validation, duplicate admission and disconnect cleanup using a fake worker.
- `python3 tests/test_native_control.py` after building the native driver: successful restoration, delayed topology after detach, bounded failure when topology never converges, rejected promotion and busy-helper admission. On macOS set `NATIVE_TEST_HELPER_IP` to a local interface address for the second simulated speaker.
- `make -C research/sonos-native/native test`: packet/clock encoding, paced PCM, opt-in recovery after a 350 ms scheduling stall, continuous packet sequence/position and timestamps after recovery, and bounded failure for a longer stall. Intercom Python tests also fill the worker pipe and verify recovery after a 200 ms stall, failure under sustained congestion, and preservation of the native error.
- `node --test airconnect-intercom.test.js` on the Protect host: real AAC decoding to PCM before end-of-input, readiness gating, credential header, refusal and decoder/socket cleanup against a mock bridge.
- `node --test airconnect-protect-integration.test.js`: camera forwarding remains active; ready is delayed until native setup; no HTTP Sonos session is created. Run beside the patched Protect module.
- Muted live test: 15-second AAC source decoded and sent 2,650,112 PCM bytes; native sender reported 3,423 UDP packets, 40 clock requests, 662,178 signal frames and zero worker queue drops. Nine packets were more than 6 ms late. Helper and receiver restoration were logged as verified, and worker exit was zero. No acoustic quality or end-to-end microphone latency claim is made from this muted test.
- Front Door recovery regression: reproduced a helper retaining the receiver in an orphaned old group after promotion. After checking each coordinator's own membership and waiting after detach, a muted 15-second AAC stream reached ready in 7.6 seconds, sent 2,650,112 PCM bytes with zero queue drops, and restored both speakers. This validates setup and transport; an audible microphone test remains necessary.

- Live microphone follow-up: after clearing an expired legacy HTTP talkback source from the stopped receiver, the user reported substantially improved Front Door playback. The unmuted session delivered 9,170,856 PCM bytes (about 52 seconds), zero worker queue drops, exit code zero and verified speaker restoration. This run preceded the additional connection diagnostics; it does not establish that the app's transient WebSocket warning is resolved.
- Stall recovery follow-up: a later microphone session ended after about 40 seconds with a worker write failure and secondary `PCM input congested` error. After adding bounded recovery, a 90-second muted Front Door stream survived an intentional 351 ms worker pause, reported one recovery and 10,716 discarded stale frames (about 243 ms), received all 15,880,192 decoded PCM bytes, exited zero and restored both speakers. Audible behavior across recovery remains to be confirmed; the test establishes continued transport, not uninterrupted sound.

AAC ingress is expected to be ADTS, matching the existing live AAC stream path. Other client codecs/containers need an explicit decoder change. Detailed audible quality, longer endurance and concurrent audible intercom/AirPlay still require user validation.

For the latest follow-up session and remaining uncertainties, see [validation](../../docs/VALIDATION.md). For logs and recovery steps, see [operations](../../docs/OPERATIONS.md).
