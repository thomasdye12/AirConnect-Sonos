# Fork changes

## Current source — 2026-10-15 (after tds4; no new binary release)

- Added the separate authenticated PCM WebSocket intercom service and native C worker, explicit room/IP admission, bounded queues, shared native leases, status and graceful restoration.
- Added the Protect AAC/FFmpeg adapter and integration patch, preserving camera talkback and waiting for speaker readiness. Connection diagnostics distinguish client, camera, decoder and bridge failures; cancellation during camera lookup no longer starts a native session afterwards.
- Added the separate read-only LAN dashboard, service/room/ownership views, recent intercom sessions and diagnostics, with an installer and component rollback.
- Fixed helper-release checks to use each speaker's own topology and wait for detach propagation, avoiding false failure from an orphaned cached group.
- Added intercom-only recovery for bounded scheduling stalls, stale PCM discard, a 750 ms pipe-backpressure bound and preservation of the underlying native error. Strict AirPlay pacing remains unchanged.
- Verified muted 90-second recovery under an intentional 351 ms worker pause. A later real microphone session completed about 69 seconds of PCM cleanly, but its client close intent and full audible result were not confirmed. See [validation](docs/VALIDATION.md).
- Reorganized documentation into fresh install/upgrade, architecture, operations and validation guides; preserved the previous README in [history](README.history.md). No new runtime deployment or binary release is implied by the documentation update.

## v1.12.4-tds4 — 2026-10-14

- Corrected native PCM continuity: advance a submitted-sample cursor rather than using packetized write return timing, avoiding repeated silent-block insertion and small hidden drops.
- Added deterministic continuity checks and counters for waiting, dropped frames and realignment. Long-term resampling/drift correction remains unfinished.
- Published ARM AirPlay binaries and the controller; these assets predate the separate dashboard/intercom work.

## v1.12.4-tds3 — 2026-10-14

- Integrated the native sender with AirPlay PCM, temporary helper-assisted setup, receiver promotion, helper release, shared ownership and verified restoration.
- Added configurable helper selection, native mode and per-room synchronization offset. FLUSH keeps the session alive with silence; disconnect/teardown closes the sink.
- Confirmed short Kitchen/Bathroom native listening tests and at least 30 seconds of iPhone AirPlay playback. Real helper setup remains necessary; native metadata/artwork and virtual enrollment remain unfinished.


## Research follow-up — 2026-10-14

Added bounded WAV music input to controller UDP tests. Inputs are validated before device access, preserve stereo PCM, and fade at both ends; audible output remains explicit. Bathroom's initial 25-second listening result was uncertain. A 30-second repeat with early helper release and an ending tone was user-confirmed clear through the end marker: 5,270 packets, 60 clock requests, zero late sends, both speakers restored. Initial helper setup remains necessary. See `bathroom-music-test.json`.

Kitchen cleanup now skips redundant membership removal only when both speakers independently report both devices standalone. This avoids aborting an already detached session. The user confirmed a clear 25-second tone at volume 35, including about 16 seconds after helper release, despite paused transport status. Initial helper-assisted setup remains necessary. Increased the explicitly requested UDP test-volume ceiling to 35; the default remains 15 and audible tests remain opt-in and bounded to 30 seconds.

Added separate pre/post-detachment sender diagnostics and an offline decoder for the traced source-state layout. The alternate handoff handler can continue after source-state parsing fails; successful control replies alone must not be interpreted as source activation. Decoder fields remain opaque where semantics are unverified. No production backend change.

Added controller `udp-test`, muted nonzero PCM, and an explicitly enabled, bounded tone listening mode. A detached receiver sustained a 120-second nonzero-PCM test but continued to report paused. Traced the reference firmware's explicit paused-state selection for source-less promotion. Source/state/volume/mute/group restoration remains mandatory; production playback is unchanged. See `detached-pcm-followup.txt`.

Two silent native UDP receivers now passed a shared-coordinator control for 90 and 150 seconds, including stopping the first while the second continued. Added a centralized three-speaker probe and four failure-path tests. Self-promotion with corrected group/membership cleanup kept UDP/timing alive for 120 seconds after releasing the helper, but Sonos reported paused and audible rendering remains unverified. Initial helper-assisted setup remains necessary. Added three checks separating sender progress from playback success. See `coordinator-role-followup.txt` for evidence and limits. Production playback is unchanged.

Ordinary group setup supported a 120-second silent native UDP stream without Connect-specific or line-in calls. Two software-source receiver streams were observed concurrently, but an isolated long run confirms a roughly 76-second orphaned-group failure. Added the bounded probe, four rollback/preflight tests, sanitized evidence and a nearby-firmware coordinator-monitor trace. This does not change the deployed tds2 bridge or establish an independent native backend.

## v1.12.4-tds2 — 2026-10-14

- Optional native room-list cache: validated coordinator data, 24-hour expiry, API URL binding, atomic private writes, current prefix/suffix applied on load.
- Companion controller for local service status/restart, API room listing and explicitly silent bounded clip experiments.
- Backup/rollback CloudKey installer preserves existing audio settings.
- Published Sonos transport research source, tests and sanitized findings under `research/sonos-native`, with an authoritative status guide.
- Verified C cache/metadata checks, HTTP fallback, 22 Python tests, native sender tests, RTSP integration, both target builds and an eight-second silent clip with state restoration.

Production audio still uses UPnP HTTP. Native UDP independent setup, virtual-player enrollment, clip-to-AirPlay integration, dynamic Sonos artwork and acoustic latency improvements are unfinished. No audible end-to-end retest was performed for tds2.

## v1.12.4-tds1

Native Sonos API coordinator naming, sender/metadata robustness, artwork reception and hosting, direct systemd startup, original attribution and reproducible dependency patch. Based on Philippe's AirConnect v1.12.4.
