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

`room` accepts a configured UUID or a case-insensitive room name. The response is `preparing`, followed by `ready` after the receiver has been promoted and the helper restored/released, or `error` if setup fails. **Do not send microphone PCM until ready.** Preparation took 4.8 seconds in the recorded lab test; this is setup time, not measured mouth-to-speaker latency. Open the intercom before beginning to talk.

Once ready, send binary frames containing raw, signed 16-bit little-endian, stereo PCM at 44,100 Hz. Payloads must be multiples of four bytes, at most 64 KiB each. The bundled adapter uses 8 KiB or smaller frames. Compression and fragmented WebSocket messages are not supported. Send ping frames during microphone pauses; the adapter sends one every three seconds. Input expires after 15 seconds without traffic/heartbeat; sessions also have a ten-minute limit. Closing the WebSocket stops the worker and attempts verified speaker restoration.

The worker primes 60 ms of PCM and caps its queue at 200 ms. It sends silence during setup/underruns, counts discarded old frames on overflow, and retains a 75 ms UDP scheduling lead. These values are not an acoustic latency guarantee. The adapter stops on excessive network/decoder backpressure rather than queueing unlimited speech. This path does not apply AirPlay's per-room video synchronization offset.

`GET /v1/status` uses the same Authorization header. The read-only dashboard reads `/run/airconnect-intercom/status.json` locally, shows current and recent intercom counters, and includes workers' actual device leases in native ownership. It never receives the intercom token.

## Bridge installation

After preparing and building the existing AirConnect source dependencies:

```sh
sh build-intercom.sh
```

This builds `bin/airconnect-intercom-worker` separately; it does not replace or restart the running AirPlay binary. On another build target, set `HOST`, `PLATFORM` and `CC`, as for the native driver. Install that executable and `tools/airconnect_intercom.py` into `/var/airplay_sonos/intercom/`. Copy [the example configuration](../../deploy/intercom.example.json) there as `config.json`, replacing its documentation addresses and room identities. The room list is explicit; update it after a name/IP change. The existing native helper JSON remains authoritative for helper identity.

Generate a random secret of at least 32 characters in the configured `token_file`. Keep the config and key readable only by the service owner. Install [airconnect-intercom.service](../../deploy/airconnect-intercom.service) in `/etc/systemd/system/`, then:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now airconnect-intercom.service
```

The supplied unit runs as root to share the existing bridge's root-owned device leases. It creates the runtime status directory and permits graceful worker restoration on shutdown. The intercom log is `/var/log/airconnect-intercom.log`; include it in the host's log rotation policy.

Sonos can acknowledge a group change before its topology updates. Setup polls after promotion and again after the recovery detach (up to three seconds per polling phase). Each speaker must report its own group as standalone, with its expected coordinator identity, address and single member. The helper's cached view of the receiver can retain an orphaned old group and is not authoritative for receiver membership. Microphone audio is accepted only after both local membership checks and helper restoration succeed. A speaker that remains grouped still causes bounded failure and restoration. Native failures identify the setup stage in the log, WebSocket error and dashboard session status; snapshot logs distinguish an active transport from a missing standalone identity.

## Protect adapter

Copy `airconnect-intercom.js` beside the existing `protect-talkback.js`; it uses that project's installed `ws` dependency and FFmpeg executable. The accompanying `protect-talkback.patch` records the integration against the inspected service. Inspect and apply with `git apply --unidiff-zero --check` first, because other versions of the project may differ. No full copy of the private Protect project is included.

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

Copy the bridge credential securely into that private key file. Protect both files with mode 0600 and exclude them from version control. `SONOS_NATIVE_CONFIG` can point to another config path. Restart the Protect service to load changes. The existing client URL and `sonosSpeaker` query parameter remain unchanged; the ready response gains `transport: "native-udp"`.

With native mode enabled, Sonos audio bypasses the HTTP `urlradio` session, its volume controls and resume polling. The native worker owns volume/restoration. No automatic fallback happens after an error, to prevent two competing backends. For rollback, set `enabled` to false and restart Protect; the original HTTP path remains in the module. Back up the current module before patching it.

## Verification

- `python3 -m unittest discover -s tests -p test_intercom.py`: masked PCM/control framing, malformed/unmasked/oversized rejection, authentication, Origin rejection, format/volume/room validation, duplicate admission and disconnect cleanup using a fake worker.
- `python3 tests/test_native_control.py` after building the native driver: successful restoration, delayed topology after detach, bounded failure when topology never converges, rejected promotion and busy-helper admission. On macOS set `NATIVE_TEST_HELPER_IP` to a local interface address for the second simulated speaker.
- `node --test airconnect-intercom.test.js` on the Protect host: real AAC decoding to PCM before end-of-input, readiness gating, credential header, refusal and decoder/socket cleanup against a mock bridge.
- `node --test airconnect-protect-integration.test.js`: camera forwarding remains active; ready is delayed until native setup; no HTTP Sonos session is created. Run beside the patched Protect module.
- Muted live test: 15-second AAC source decoded and sent 2,650,112 PCM bytes; native sender reported 3,423 UDP packets, 40 clock requests, 662,178 signal frames and zero worker queue drops. Nine packets were more than 6 ms late. Helper and receiver restoration were logged as verified, and worker exit was zero. No acoustic quality or end-to-end microphone latency claim is made from this muted test.
- Front Door recovery regression: reproduced a helper retaining the receiver in an orphaned old group after promotion. After checking each coordinator's own membership and waiting after detach, a muted 15-second AAC stream reached ready in 7.6 seconds, sent 2,650,112 PCM bytes with zero queue drops, and restored both speakers. This validates setup and transport; an audible microphone test remains necessary.

AAC ingress is expected to be ADTS, matching the existing live AAC stream path. Other client codecs/containers need an explicit decoder change. Actual iPhone microphone playback, audible quality, longer endurance and concurrent audible intercom/AirPlay still require user validation.
