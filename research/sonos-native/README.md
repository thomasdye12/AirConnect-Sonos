# Sonos transport research

These are research tools alongside AirConnect-Sonos, not an installed AirPlay output backend. Start here instead of the chronological notes. Latest follow-up: [coordinator role and concurrent receivers](firmware-research/coordinator-role-followup.txt) verifies two bounded silent streams with a retained real coordinator. A promoted standalone receiver also kept UDP/timing alive for 120 seconds after releasing its helper, but reported paused and has no audible validation. Fully independent setup remains unresolved. No virtual player needs to run for normal AirConnect playback.

| Path | Evidence | Remaining work |
| --- | --- | --- |
| Normal AirConnect UPnP HTTP | Existing deployed bridge; user-confirmed music | Dynamic artwork and acoustic latency improvements |
| Native UDP PCM | Historical clear music with Connect setup; silent ordinary-group receivers ran for 90 and 150 seconds, with one stopping while the other continued; no Connect or line-in calls | Synthetic coordinator times out around 76 seconds. Self-promotion kept a detached endpoint alive for 120 seconds but reported paused; audible rendering, helper-free bootstrap, recovery, drift and AirPlay integration remain unfinished |
| Local API HTTP audioClip | Silent finite streams of 12 and 40 seconds; lengthless streams; separate streams/cancellation on two speakers without Connect | Listening test, longer endurance, actual latency, AirPlay integration and volume/metadata behavior |
| Virtual Connect | Discovery/descriptor/TLS observer and compatibility tests | Trusted enrollment and playback; app crashes occurred during earlier experiments |

A 75 ms native packet timestamp lead is not a measured audio latency. An `ACTIVE` clip event is not evidence of audible playback. Concurrent loopback senders are not proof of multiple independent native speaker sessions.

## Build and offline checks

Python 3.8+ and a C99 compiler with POSIX sockets/pthreads are required. These tests bind local sockets but do not configure a speaker:

```sh
make -C native all test
python3 -m unittest discover -s . -p 'test_*.py'
python3 -m unittest discover -s virtual-connect -p 'test_*.py'
```

`native/INTEGRATION.txt` documents the PCM boundary, ownership, clock ports and cancellation requirements for a future backend. `linein.py` decodes the observed classic-pcap format; arbitrary pcapng input is not supported.

## Bounded clip test

From the repository root:

```sh
python3 tools/airconnectctl.py clip-test --receiver SPEAKER_IP --receiver-id SPEAKER_UUID --seconds 12 --streaming --output work/clip-test.json
```

The command is explicitly silent, requires a stopped standalone receiver and checks source, transport, volume, mute and topology restoration. It runs a temporary local HTTP server, accepts its receiver's requests, and cancels only the clip ID it created. Python 3.8+ is needed; use a Mac or modern Linux host rather than the legacy CloudKey Python. The local API client accepts self-signed speaker certificates without verification and is a LAN research client. It sends no account credentials. JSON output includes household/device data and belongs in private `work/` storage.

For audible experiments, `clip_stream_probe.py` separately requires `--audible --wav YOUR_FILE.wav` (44.1 kHz stereo signed 16-bit PCM) and caps volume at 25. Do not run it without arranging a listening test. Neither importing nor running the controller starts an audible test; run the probe as a script, not an importable library.

## Native and virtual-player experiments

`probe.py` is the bounded Connect-assisted native test. Read its `--help` and `native/INTEGRATION.txt` before using it; it temporarily changes receiver grouping/source and attempts restoration. `discovery_probe.py` is an incomplete discovery stub, not a working Connect replacement.

`virtual-connect/virtual_connect.py` defaults to local inspection. LAN advertisement requires explicit `--advertise`; pairing and audio are not implemented. The original machine-specific auto-advertising launcher is intentionally omitted. Generated identities, certificates, private keys and observed reference profiles must remain outside the repository.

## Findings and provenance

- [Latest stream tests](firmware-research/streaming-input-tests.txt) and [structured results](firmware-research/streaming-input-tests.json).
- [Current feasibility](firmware-research/current-feasibility.txt), [native playback](firmware-research/native-playback-result.txt), [receiver handoff](firmware-research/receiver-handoff-followup.txt).
- Remaining notes describe chronological investigations, including failed or superseded hypotheses. Firmware offsets refer to named builds, not a universal protocol specification.
- Static firmware reference: trulyspinach/sonos-fenway, commit `b01d1cf7eed34988e15a8208034d2e5a400efde7`. Newer static evidence used 86.10-81100; live speakers ran 86.10-80260. No firmware was flashed.
- Local API wire-format reference: jjlawren/sonos-websocket, commit `454c2b8c977537df8d9c2ac155a1e4f244eb40b8`; implementation here is independent standard-library Python.
- See [repository attribution](../../NOTICE.md) for original AirConnect credit and licensing.

The archive includes original source and sanitized research notes. Raw captures/HAR/crash files, recordings, disassembly dumps, firmware, account secrets, real household/device identities and local state are excluded. Paths mentioned by historical notes may refer to private evidence that is not distributed. Example IP addresses use the documentation range.

## Ordinary-group UDP probe

Python 3.8+ and the built native library are required. Both devices must initially be stopped and standalone. This changes grouping temporarily, sends silence, and restores/verifies both devices:

```sh
python3 group_receiver_probe.py --receiver SPEAKER_IP --receiver-id SPEAKER_UUID --coordinator HELPER_IP --coordinator-id HELPER_UUID --seconds 120 --output PRIVATE_RESULTS.json
```

`--handoff-to-synthetic --release-coordinator --reset-helper-group` investigates the orphaned-group failure; it is expected to fail the longer test. These flags do not enroll a virtual Sonos device. Do not run multiple probe processes against a shared helper without coordinating their setup and restoration; this standalone harness is not a session manager.

`--promote-receiver --promotion-mode detach --seconds 120` tests promotion of an active receiver to its own group and removal of the helper. UDP/timing persisted for 120 seconds, but Sonos reported `PAUSED_PLAYBACK`: the command intentionally exits nonzero because the playback check fails. Sender progress is recorded separately from playback success. No audible result is claimed. Initial setup still needs the helper. Mode `retain` keeps the inherited group; mode `resume` additionally requests Play, which ended the native stream in the observed test. Kitchen's detach attempt returned 800 during helper cleanup, so this sequence is not portable or ready to deploy.

For the shared-coordinator concurrency control, one process must own all three devices:

```sh
python3 multi_receiver_probe.py --first SPEAKER_A_IP --first-id SPEAKER_A_UUID --second SPEAKER_B_IP --second-id SPEAKER_B_UUID --coordinator HELPER_IP --coordinator-id HELPER_UUID --seconds 150 --first-stop 90 --output PRIVATE_RESULTS.json
```

All three must be stopped and standalone. The command uses silence and mute, detaches/stops the first receiver, checks the second keeps playing, and restores/verifies all devices. It caps duration at 180 seconds. Do not overlap it with other speaker probes. Both receivers share a real coordinator; this does not implement independent virtual players, separate AirPlay sessions or an installed controller backend. The recorded run had one late sender packet, and no audible continuity test.

### Controller test command and nonzero PCM

The controller now exposes the ordinary and detached experiments from a full checkout on a Mac or modern Linux test host. Build the local C library first:

```sh
make -C research/sonos-native/native
python3 tools/airconnectctl.py udp-test --receiver SPEAKER_IP --receiver-id SPEAKER_UUID --coordinator HELPER_IP --coordinator-id HELPER_UUID --mode detach --signal tone --seconds 120 --output PRIVATE_RESULTS.json
```

This sends a quiet 440 Hz PCM signal **with both speakers muted**. Unlike zero PCM, the signal exercises near-full audio datagrams. Both speakers must start stopped and standalone. The command snapshots and restores their source, transport, volume, mute and grouping. It requires Python 3.8+ and a locally built native library. It does not restart AirConnect or install a native backend.

For a listening test, use `--seconds 25 --audible --test-volume 15`. Only an explicit `--audible` unmutes the receiver; the helper stays muted. Audible tests are limited to 30 seconds and volume 25. With `--mode detach`, the first eight seconds provide an ordinary-group reference, followed by promotion and helper release. Listen for whether the tone continues after the transition, and whether it clicks or breaks up. Promotion time is recorded; `--promotion-delay` adjusts it. The default fade is 200 ms at each end. No Play command is sent after detachment.

The new nonzero-PCM detached test lasted 120 seconds, with 21,083 packets and 135 timing replies, but still reported paused. Three sends exceeded the six-millisecond deadline tolerance; these are sender timing observations, not measured audio dropouts. The CLI intentionally returns failure for paused transport even when sender progress succeeds. No automated result claims acoustic playback. See [the follow-up](firmware-research/detached-pcm-followup.txt).
