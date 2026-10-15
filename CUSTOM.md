# Build and validation details

This document covers the current fork build and records the tds3/tds4 timing changes. For fresh installation, use [INSTALL.md](docs/INSTALL.md); for current evidence, use [VALIDATION.md](docs/VALIDATION.md). See [README.md](README.md) for status and [NOTICE.md](NOTICE.md) for provenance.

## Source preparation

Run `sh prepare-source.sh` after cloning. Only pinned top-level submodules are required; full recursive initialization downloads many unrelated development repositories. The script applies the included RAOP patch and checks whether it has already been applied.

The AirUPnP Makefile accepts `RAOP_LIBRARY` so custom builds link the recompiled library rather than silently using upstream's unchanged archive. Both build scripts set this explicitly.

## Build targets

- `build-custom.sh`: Clang/macOS ARM64 by default. Recompiles the RAOP library, then regular and static AirUPnP variants. `CC`, `CXX`, `HOST`, and `PLATFORM` can override the defaults when matching dependency archives/toolchains are available.
- `build-cloudkey.sh`: GCC/Linux ARM hard-float. Recompiles `raop_server.c` and `raop_streamer.c`, updates a copy of the matching upstream RAOP archive, then links regular and static binaries. Tested with GCC 4.9 on Debian 8. This avoids unrelated C++17 client sources.

Both use upstream dependency archives. Existing compiler warnings remain; static linking has the usual upstream glibc/DNS/dlopen limitations. Successful `-h` execution is a smoke test, not complete playback validation.

## Tests

For native lifecycle, intercom and dashboard coverage/commands, see [the current validation guide](docs/VALIDATION.md#automated-checks). The commands below focus on the original naming/metadata work.

On macOS ARM64 after building:

```sh
sh tests/run.sh
sh tests/run-rtsp.sh
```

The first script uses AddressSanitizer and UndefinedBehaviorSanitizer for the new parser/formatting paths. It covers coordinator-only selection, special characters in room names, invalid and duplicate responses, atomic snapshot replacement, missing metadata fields, long titles, UTF-8 truncation, quote handling, and supported image types/size limits.

The RTSP test invokes the real SET_PARAMETER handler on loopback sockets. It covers PNG/JPEG reception, sender fallback, title updates, image replacement, and explicit artwork clear. It does not claim end-to-end Sonos artwork display and does not stream audio to speakers.

A read-only real API test can be added with:

```sh
tests/bin/test_sonos_api http://sonos-api.local:5005/zones
```

The parser/format tests and API request were also run natively on a CloudKey. Both ARM binaries executed there; discovery found 19 coordinators and the installed service advertised them over AirPlay. Basic playback was confirmed by the user. Artwork in Sonos did not display; title/artist display needs further validation. No acoustic latency improvement has been measured.

## Operational behavior

- API room names/membership are loaded once per start, matching the previous external-generator workflow. Restart after room/group changes.
- If the configured API is unavailable/invalid, a validated API-bound cache less than 24 hours old can be used. Without a usable cache, startup fails and systemd retries after 30 seconds.
- API names override per-device enabled/name settings when the API option is present.
- Sender names come from AirPlay request headers; IP is the fallback. mDNS hostname fallback is not implemented.
- Current received artwork is retained until replacement, explicit clear, teardown, or receiver destruction. Images are capped at 4 MiB. Sources that never send artwork cannot supply a cover through this mechanism.
- MP3/AAC metadata uses ICY. Sonos reads StreamTitle but not the StreamURL artwork field; the experimental image support is therefore not a working Sonos dynamic-artwork implementation.

## Latency

Use repeated listening or acoustic timing tests with the same source/speaker. Measure startup delay separately from steady-state delay and record dropouts. The public example uses upstream's conservative `1000:2000` setting; smaller buffers may reduce buffering or may produce underruns. FLAC with small blocks is another audio experiment, but live ICY metadata is available only with MP3/AAC in this bridge. No particular setting is guaranteed to minimize total Sonos latency.


Native AirPlay output (tds3)
--------------------------
The shipped libraop patch adds an optional PCM sink without changing the existing
`raopsr_create` HTTP entry point. `raopsr_create_pcm` passes callbacks to a dedicated
output thread; decoded samples are copied under the ingest mutex and written
outside it. Failed sinks close once. FLUSH preserves the sink with silence, and
TCP disconnect/TEARDOWN closes it. The new Sonos implementation is POSIX C and
builds on the tested macOS ARM64 and Linux ARMv7 targets.

`airupnp/src/sonos_native.c` implements bounded SOAP setup, same-host device leases,
background promotion, helper release, volume updates and verified restoration.
The normal UPnP polling and source Play/Stop path are bypassed for native receivers.
The chosen helper is not advertised when common native mode is enabled. Saved
helper JSON and generated household logs are private and excluded from releases.

Native mode is opt-in (`native_udp`, `native_muted`, `sonos_native_helper`). The
controller exposes `helper-set`, `helper-show` and `native-mode`; restart applies
changes. Per-device overrides keep grouped rooms on HTTP. Source title/artwork
updates are not implemented for the native path. It is not helper-free bootstrap,
AirPlay 2 synchronized multiroom, or an acoustic latency guarantee.

Native timing uses the source sync-packet latency plus the receiver delay sent in
RECORD. Decoded audio waits for its presentation deadline minus the sink's 75 ms
lead. Setup cannot trim future audio; only expired complete frames are dropped.
Native mode ignores the HTTP hold-depth component and bypasses the HTTP drift
adjustment, since the PCM output uses presentation timestamps directly. This is
partial scheduling, without speaker DAC feedback or resampling. The protocol
interpretation is consistent with [Shairport Sync's RECORD handler](https://github.com/mikebrady/shairport-sync/blob/master/rtsp.c)
and [sync-packet handling](https://github.com/mikebrady/shairport-sync/blob/master/rtp.c).
`native_sync_offset_ms` adds bounded local calibration (-1000..5000 ms) without
changing RECORD's advertised delay. Positive values delay presentation; the
common default is zero and device overrides are supported. The user reported
roughly 500 ms early audio and a two-second pause tail after the initial timing
fix. Kitchen received a 500 ms calibration for a further check at that stage. Those were historical calibration observations, not recommended defaults. Later
FLUSH/pause work improved the tail according to the user; exact tap-to-silence
latency remains unmeasured and source-dependent.

Native continuity correction (tds4)
---------------------------------
The tds3 scheduler incorrectly compared the next decoded frame with the time at
which `sonos_sender_write` returned. The sender accepts 352-sample input blocks
but emits complete 251-sample packets, so that return can precede the next input
sample by several milliseconds. Inserting a whole silent block on this path
corrupted audio and could cause a subsequent frame drop. The old counters did
not expose these insertions or drops of four or fewer frames.

The output thread now anchors a local cursor at first submission and advances
it by all submitted samples, including silence. FLUSH preserves that output
clock and resets input alignment. Once aligned, clock differences within 20 ms
do not alter contiguous PCM. Larger discontinuities re-anchor with explicit
logs; final counters include waiting blocks, dropped frames and realignments.
This does not implement resampling or prove long-term drift-free playback.
