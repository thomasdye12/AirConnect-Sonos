# Fork changes

## Research follow-up — 2026-10-14

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
