# AirPlay 2 frontend assessment

Initial design assessment, 2026-10-15. The frontend backend and timed worker are now implemented experimentally; see [build and test notes](../../integrations/airplay2/README.md). The architecture discussion below records the original assessment, not a claim of completed end-to-end validation.

## Recommended approach

Use Shairport Sync for receiving AirPlay 2, with an AirConnect Sonos output backend. Preserve the existing room selection, helper setup, UDP packet/clock implementation, ownership and restoration. Begin with one separately named test destination, then add independent room instances.

The reviewed upstream revisions are:

- [Shairport Sync](https://github.com/mikebrady/shairport-sync/commit/cf6998daa1876c5a8f97128a960c8afc0e731841): `cf6998daa1876c5a8f97128a960c8afc0e731841`, configure version 5.6.
- [NQPTP](https://github.com/mikebrady/nqptp/commit/ab8fb67483411640fd7f1e193889482f2421c37c): `ab8fb67483411640fd7f1e193889482f2421c37c`, latest commit describes 1.2.9.

Downloaded source was inspected separately; no upstream implementation was copied into this repository.

## What the code provides

Shairport Sync's [audio output interface](https://github.com/mikebrady/shairport-sync/blob/cf6998daa1876c5a8f97128a960c8afc0e731841/audio.h) supplies preparation, format negotiation, timed PCM, flush/stop and volume hooks. This is a practical boundary for a custom backend. Its [AirPlay 2 guide](https://github.com/mikebrady/shairport-sync/blob/cf6998daa1876c5a8f97128a960c8afc0e731841/AIRPLAY2.md) describes realtime/buffered input, format conversion and Home integration, with limitations. These are upstream capabilities, not yet verified through Sonos.

Our `sonos_native_output()` already returns open/write/close callbacks, but accepts raw PCM without explicit presentation timestamps. The sender schedules against its own local clock. Reusing this implementation needs a timing adapter, not just swapping the network receiver.

The [pipe backend](https://github.com/mikebrady/shairport-sync/blob/cf6998daa1876c5a8f97128a960c8afc0e731841/audio_pipe.c) discards timestamp/playtime arguments, leaves the pipe open on stop and has no flush callback. A FIFO could prove basic decoding, but would not be evidence of synchronized playback or reliable pause control. The live intercom worker is also unsuitable unchanged: it primes a speech queue, discards stale input, has a ten-minute cap and enables scheduling recovery that can shift playback.

## Proposed backend contract

1. **Format:** expose only 44,100 Hz, two channels, S16_LE to match the native Sonos sender. Let the frontend convert other input formats. In particular, do not reinterpret 48 kHz/S32 data as 44.1 kHz/S16. This path would not preserve 24-bit/48 kHz lossless output.
2. **Prepare:** acquire existing leases and complete bounded helper-assisted setup. While preparing, avoid unlimited audio accumulation; discard expired samples using their intended presentation time. Cancel and restore if the source disconnects. Verify how frontend preparation failures are propagated before relying on its hook return value.
3. **Timing:** carry presentation time and frame sequence into a bounded output queue. Convert clock domains explicitly: upstream uses a raw monotonic clock on supported Linux systems, while our sender uses CLOCK_MONOTONIC. Establish and refresh the relationship; do not subtract timestamps from unrelated clocks. Preserve a continuous sample timeline and account for packet lead/calibration.
4. **Flush and stop:** clear queued audio on flush while maintaining required native silence/clock service. Stop closes the session and verifies restoration. Session generations must prevent old buffered audio from crossing a seek/reconnect boundary.
5. **Volume:** choose one primary volume path and apply a configured ceiling. Avoid applying the same attenuation in both frontend software volume and speaker volume. Initially keep metadata available for monitoring; Sonos title/artwork remains separate work.
6. **Errors:** propagate queue overflow, failed preparation, lost timing and native sender failure to the session owner. Do not silently switch output or report fabricated DAC delay statistics.

## Independent rooms and timing daemon

Upstream documents [one process per room](https://github.com/mikebrady/shairport-sync/blob/cf6998daa1876c5a8f97128a960c8afc0e731841/ADVANCED%20TOPICS/RunningMultipleInstances.md), distinct identities/endpoints and one shared multi-client NQPTP daemon. Generate stable identity and timing-interface names from room UUIDs so renaming a room need not change its identity. Reserve ports and exclude the helper. Avoid publishing both old and new receivers for the same production room during migration.

The inspected NQPTP source has `MAX_CLIENTS=16`. Review allocation/release and size this deliberately before promising a larger installation. Independent clock state matters: stopping one room must not clear another room's timing. Separate frontend instances do not remove the shared helper's serialized preparation or prove acoustic synchronization between Sonos devices.

NQPTP needs exclusive UDP 319/320 access and local timing IPC. Keep it alongside the frontend. Sharing the same host with the native sender is the simplest initial clock/lease arrangement. Moving the frontend to another host would require a timestamped transport and cross-host clock mapping; the existing raw PCM WebSocket is insufficient for that guarantee.

## Build and distribution

The current CloudKey deployment is an old ARMv7/Debian 8 environment. Upstream's [build guide](https://github.com/mikebrady/shairport-sync/blob/cf6998daa1876c5a8f97128a960c8afc0e731841/BUILD.md) targets newer systems; current source needs FFmpeg, libplist >=2.0, libsodium, libgcrypt and other development dependencies. A compatible build has not been demonstrated on the CloudKey. Do not upgrade its OS or replace production dependencies as an incidental build step.

On the local development Mac, FFmpeg, libsodium and libplist were discoverable through pkg-config, but libconfig, popt and libgcrypt were not. Those missing local libraries were subsequently installed and the frontend/timing daemon built on Apple Silicon. The initial assessment itself did not include an end-to-end playback result.

Shairport Sync includes MIT-style and component-specific notices in [LICENSES](https://github.com/mikebrady/shairport-sync/blob/cf6998daa1876c5a8f97128a960c8afc0e731841/LICENSES). NQPTP carries [GPLv2](https://github.com/mikebrady/nqptp/blob/ab8fb67483411640fd7f1e193889482f2421c37c/LICENSE). Keep its daemon/source/license packaging distinct and retain third-party notices; do not label the entire distribution MIT-only.

## Acceptance sequence

- Build the pinned frontend/timing pair and exercise a synthetic backend offline: format negotiation, deadline conversion, buffering, flush, stop, cancellation and failure propagation.
- Advertise one temporary test endpoint only after the output backend is ready. Verify iPhone discovery/pairing, realtime and buffered audio, volume/mute, pause/seek/reconnect and receiver/helper restoration.
- Confirm one-room sound and measure timing; frontend support alone is not an acoustic latency result.
- Test different phones feeding two different rooms; stop and reconnect either while the other continues. Then test one phone selecting both rooms, measuring drift and relative acoustic timing rather than assuming sync.
- Run sustained tests, helper contention, source loss and service restart before enabling per-room opt-in configuration/dashboard support. Keep the existing frontend as an explicit rollback option.

AirPlay 2 is a feasible frontend direction based on these interfaces. It does not by itself remove the real Sonos helper, solve native artwork or guarantee lower latency. The first deliverable should be a working single-room experimental backend, not a renamed AirPlay 1 advertisement.
