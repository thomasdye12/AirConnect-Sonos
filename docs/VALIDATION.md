# Validation and known limitations

This records runtime observations through October 18, 2026. The published tds4 AirPlay binaries predate the intercom, topology, recovery and native clock corrections in current source. The tests below are evidence from specific runs, not a claim that every platform, speaker model or network is supported.

## What was observed

| Test | Result | What it establishes |
| --- | --- | --- |
| Helper-assisted Kitchen tone, 25 seconds | Listener confirmed clear through the full run, including after helper release | Audible native UDP after temporary helper setup |
| Bathroom music with an ending tone, 30 seconds | Listener confirmed clear music and ending marker | Audible music through the end; an earlier 25-second run had ambiguous feedback |
| iPhone AirPlay to Kitchen | Listener confirmed at least 30 seconds of clear playback | Integrated AirPlay → native PCM → Sonos path works in this deployment |
| AirPlay timing/pause follow-ups | User reported improved synchronization and pause tail; later roughness led to tds4 cursor correction | Useful listening feedback, not a calibrated acoustic latency measurement or long-term drift test |
| Initial muted intercom, 15 seconds | 2,650,112 decoded PCM bytes, 3,423 packets, 40 clock requests, zero queue drops; both devices restored | Decoder, transport and restoration; not sound quality |
| Intercom topology checks | Muted runs passed after checking each speaker's own group and waiting for detach propagation | Covers observed stale topology; not a guarantee for all firmware |
| Live intercom | Short audible sessions worked; a later session ended with a worker/congestion error | Supports the feature's usefulness but not universal reliability |
| Recovery regression, 90-second muted stream | Survived an intentional 351 ms worker pause, with one recovery, stale PCM discarded, clean exit and speaker restoration | Continued transport through a bounded stall; audible continuity remains unverified |
| Subsequent live input | Completed cleanly with no reported queue drops or recovery | Full audible quality and the reason for client closure were not confirmed |
| Updated native handoff in AirPlay | 30-second native and 40-second full AirPlay muted checks passed; listener reported improved playback but a later dropout after several minutes | Fixes the observed early controller failure; does not establish long-duration audible reliability |
| Native clock fraction correction | C packet/sender tests, Python transport tests and native ARM packet tests passed | Standard NTP fractions and continuity across second boundaries; audible endurance still needs confirmation |

Separate silent receiver streams and independent stopping were exercised during research. Concurrent **audible** AirPlay/intercom endurance still needs validation. Older helper-free/synthetic-coordinator experiments failed around 76 seconds; those historical failures are not the same setup as the current helper-assisted promotion path.

## Clock correction, October 18

The native clock responder previously encoded microseconds with a 12-bit left shift. NTP instead uses a 32-bit binary fraction of a second: `(microseconds << 32) / 1000000`, evaluated with 64-bit arithmetic. The old approximation introduced a repeating error of up to 46.3 ms and a jump at each second boundary. Re-analysis of 115 real Sonos replies supported standard NTP decoding: capture-to-source offset standard deviation was approximately 0.16 ms, versus 15.93 ms under the previous interpretation. This corrects an earlier research inference and its matching test fixture.

The C sender and Python research responders now use standard fractions. Tests independently assert half- and quarter-second values and microsecond continuity through a rollover. Native control also reports packet, clock-reply and late-packet counts every 30 seconds. These counters show transport activity; they cannot prove that the speaker renders audio. The clock bug is a plausible explanation for later silence, but the reported long-session dropout is not considered acoustically resolved until a listener confirms sustained playback after the fix.

## Automated checks

The implementation was exercised on Apple Silicon macOS and the ARMv7 CloudKey. These commands are for developers from the repository root after [preparing/building source](INSTALL.md); they are not required on an installed runtime host.

```sh
sh tests/run.sh
sh tests/run-rtsp.sh
sh tests/run-pcm.sh
python3 -m unittest discover -s tests -p 'test_controller.py'
python3 -m unittest discover -s tests -p 'test_intercom.py'
python3 -m unittest discover -s tests -p 'test_dashboard.py'
make -C research/sonos-native/native test
sh tests/build-native-driver.sh
python3 tests/test_native_control.py
```

Some harnesses use modern Python or platform-specific compiler/sanitizer settings; the service's Python 3.4 support is not a promise that all research/test tools run on Python 3.4. For macOS native-control simulation, set `NATIVE_TEST_HELPER_IP` to a local interface address to distinguish the second simulated speaker. Review scripts before running on a different platform.

Coverage includes room/cache parsing, metadata and actual RTSP handlers, PCM continuity, packet/clock encoding, native lifecycle, delayed topology convergence, bounded topology failure, rejected promotion, busy-helper refusal, WebSocket authentication/framing, room admission, disconnect cleanup and dashboard responses. Scheduling tests distinguish a recoverable 350 ms intercom stall from strict AirPlay pacing and a longer 700 ms failure. Pipe tests distinguish a transient 200 ms stall from sustained congestion and verify the original native error survives.

## Remaining work

- Confirm audible continuity during recovery and investigate any repeated app-side disconnects with both sets of logs.
- Measure mouth-to-speaker latency, A/V offset and pause tail separately; packet lead or setup duration cannot substitute for those measurements.
- Run longer audible endurance and independent simultaneous sessions on more speaker models/firmware versions.
- Add long-term drift correction if measurements demonstrate it is needed; current output has no resampling-based DAC feedback loop.
- Implement/validate native track information and artwork; current artwork reception does not provide working Sonos display.
- Complete helper-free setup/enrollment research if feasible. The real helper remains an installation requirement today.

Research captures, firmware, private configuration and test music are intentionally excluded. See [research provenance](../NOTICE.md) and the [historical research guide](../research/sonos-native/README.md) for source tools and sanitized evidence.
