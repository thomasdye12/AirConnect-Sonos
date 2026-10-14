# Sonos transport research

These are research tools alongside AirConnect-Sonos, not an installed AirPlay output backend. Start here instead of the chronological notes. Latest follow-up: [ordinary-group UDP tests](firmware-research/ordinary-group-udp-tests.txt) remove the Connect-specific requirement, but sustained operation still needs a valid real coordinator. No virtual player needs to run for normal AirConnect playback.

| Path | Evidence | Remaining work |
| --- | --- | --- |
| Normal AirConnect UPnP HTTP | Existing deployed bridge; user-confirmed music | Dynamic artwork and acoustic latency improvements |
| Native UDP PCM | Historical clear music with Connect setup; now a 120-second silent run with an ordinary stopped coordinator, no line-in calls; two temporary software-source streams observed concurrently | Software-coordinator streams time out around 76 seconds; independent setup, recovery, drift and AirPlay integration remain unfinished |
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
