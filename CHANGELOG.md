# Fork changes

## v1.12.4-tds2 — 2026-10-14

- Optional native room-list cache: validated coordinator data, 24-hour expiry, API URL binding, atomic private writes, current prefix/suffix applied on load.
- Companion controller for local service status/restart, API room listing and explicitly silent bounded clip experiments.
- Backup/rollback CloudKey installer preserves existing audio settings.
- Published Sonos transport research source, tests and sanitized findings under `research/sonos-native`, with an authoritative status guide.
- Verified C cache/metadata checks, HTTP fallback, 22 Python tests, native sender tests, RTSP integration, both target builds and an eight-second silent clip with state restoration.

Production audio still uses UPnP HTTP. Native UDP independent setup, virtual-player enrollment, clip-to-AirPlay integration, dynamic Sonos artwork and acoustic latency improvements are unfinished. No audible end-to-end retest was performed for tds2.

## v1.12.4-tds1

Native Sonos API coordinator naming, sender/metadata robustness, artwork reception and hosting, direct systemd startup, original attribution and reproducible dependency patch. Based on Philippe's AirConnect v1.12.4.
