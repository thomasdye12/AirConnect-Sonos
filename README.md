# AirConnect-Sonos

A modified fork of **[Philippe's AirConnect](https://github.com/philippe44/AirConnect)**, maintained by [Thomas Dye](https://github.com/thomasdye12), with native Sonos HTTP API room naming, metadata improvements, and optional helper-assisted native UDP AirPlay output.

**This is a copy of and derivative work based on AirConnect, not an independently created AirPlay implementation.** The original bridge, discovery, codecs, and protocol work belong to their respective upstream authors. This fork is not an official AirConnect, Sonos, or Apple release.

Based on AirConnect v1.12.4 at [`5fdb61e`](https://github.com/philippe44/AirConnect/commit/5fdb61e20de59bac5dbda9f6e2ed56ce549ccabd). The original documentation is preserved in [README.upstream.md](README.upstream.md). See [NOTICE.md](NOTICE.md) and the original [LICENSE](LICENSE) for attribution and dependency licensing.

## What this fork changes

- **Native room naming from a Sonos HTTP API:** reads `/zones` directly, publishes group coordinators, and applies configurable name prefixes/suffixes such as `Kitchen (Sonos)`. No PHP configuration-generation script is required.
- **Validated startup room list and optional cache:** rejects invalid, duplicate, empty, or oversized API responses. A configured cache can recover from an API outage using the last validated coordinator list for up to 24 hours. With the supplied systemd unit, failed starts retry after 30 seconds.
- **Sender fallback:** uses the name in the AirPlay request when available, otherwise the sender IP. Discovery-based friendly iPhone names are **not implemented yet**.
- **Metadata handling:** bounded ICY fields, safe handling of missing fields, retained metadata across HTTP reconnects, and safe text insertion in initial UPnP metadata.
- **Experimental artwork reception:** accepts JPEG/PNG sent by the AirPlay source and serves the current image for the session instead of expiring it after two minutes. Image updates get distinct URLs.
- **Direct systemd startup:** uses `-Z` for non-interactive operation, avoiding the original local shell/PHP launcher and its observed excessive CPU usage. Logging is capped at 5 MB.

## Native UDP AirPlay (tds3)

The bridge can now send decoded AirPlay PCM directly to Sonos over UDP. A user-selected, stopped Sonos helper briefly establishes each receiver, then is restored and released while audio continues. Concurrent receivers serialize helper setup and keep independent audio/timing sessions. This is experimental and opt-in; HTTP output remains available.

On the bridge host after installing a tds3 build:

```sh
python3 /var/airplay_sonos/airconnectctl.py helper-set --address HELPER_IP
python3 /var/airplay_sonos/airconnectctl.py native-mode --enabled 1
python3 /var/airplay_sonos/airconnectctl.py restart
```

`helper-set` saves the helper's verified IP, UUID and room name in `native-helper.json`. The helper is reserved from AirPlay advertisement when common native mode is enabled. It must be stopped and standalone when another receiver starts. Update the helper address and restart after an IP change. The JSON path can be set with `--helper-config` and the XML `sonos_native_helper` element.

The receiver must also be stopped and standalone. Native mode does not break up an existing speaker group or take over unrelated playback. Leave grouped rooms on HTTP with `<native_udp>0</native_udp>` in their `<device>` configuration. Common settings set the default; device overrides take precedence. `native-mode --enabled 0` returns the default to HTTP after a restart. The installer does not silently opt into native mode.

Each AirPlay source selects its own advertised room. This supports separate streams to different receivers; it does not add AirPlay 2 synchronized multi-destination playback. FLUSH clears queued AirPlay frames while the native connection sends silence; audio resumes on new frames. TEARDOWN, a closed AirPlay TCP connection, service shutdown and sender errors close the session and attempt verified state restoration. Helper setup waits at most 15 seconds for each device lease; SOAP calls have bounded network waits. A failed native session logs an error and requires reconnecting; it does not silently fall back or claim audible playback.

[ARM integration evidence](research/sonos-native/firmware-research/airplay-native-integration.json) records two overlapping muted AirPlay streams, pause/resume, helper reuse, nonzero decoded PCM, abrupt TCP disconnect and independent restoration. Earlier short direct UDP tone/music tests were listener-confirmed. After installation, the user confirmed clear iPhone AirPlay playback in Kitchen for at least 30 seconds. That initial build played audio ahead of a YouTube sync test; after the timestamp correction below, the user reported audio approximately 500 ms early and about two seconds of sound after pause. A local 500 ms calibration was then applied for a repeat sync check. The pause tail remains unresolved. Measured acoustic latency, audible concurrent iPhone streams and long endurance remain unverified. Sonos still reports paused during native rendering; native mode suppresses the old transport-poll feedback that would pause the AirPlay source. Native title/artwork updates are not implemented.

For silent validation use `native-mode --enabled 1 --muted` and restart. Remove `--muted` when enabling normal playback. The original `1000:2000` profile belongs to HTTP output; the integrated tests used `500:0`. Native output follows the source RTP/NTP presentation schedule, including the receiver delay advertised in RECORD. It submits PCM 75 ms before that time to account for the UDP sender lead, preserves future frames through helper setup, and discards only expired complete frames. This replaces the initial 32-packet startup trim. It is not a measured end-to-end delay or proof of video lip-sync. The native sender stops on a producer stall exceeding 250 ms rather than bursting stale audio.

Local A/V calibration is available as `native-mode --enabled 1 --sync-offset-ms 500`, followed by a restart. The range is -1000..5000 ms; positive values delay audio, zero is the default, and omitting the option preserves the saved value. This offset changes local presentation only, not the latency advertised to the source. To calibrate one receiver, put `<native_sync_offset_ms>500</native_sync_offset_ms>` in its `<device>` entry. A source that does not send an immediate FLUSH can leave queued audio playing after pause; calibration does not solve that pause tail.

## Important limitations

**Changing artwork in the Sonos app does not work in this version.** Receiving/hosting an image is not proof that Sonos displays it. The current MP3/AAC ICY path sends artwork as `StreamURL`; Sonos documents that its ICY parser reads only `StreamTitle`. Its documented dynamic-artwork route is HLS/ID3 metadata, which this fork does not implement. See [Sonos's audio-format documentation](https://docs.sonos.com/docs/supported-audio-formats).

Basic audio playback and API room naming were verified on a first-generation UniFi CloudKey. Automated tests verify metadata handling, but end-to-end Sonos title/artist updates are not fully validated. The room list is a **startup snapshot**: restart after API room/group changes. The optional cache may be stale after a group change; restart with a working API to refresh it. An empty `sonos_cache` disables fallback.

No reduction in audible latency is claimed. Sonos buffering remains relevant; this is not a video lip-sync solution. The configuration example uses the upstream-recommended `1000:2000` Sonos buffer profile. Lower settings need listening tests on your network.

## Download

See [Releases](https://github.com/thomasdye12/AirConnect-Sonos/releases) for the experimental ARM hard-float CloudKey build. Prefer `airupnp-linux-arm`; the static variant is a fallback. Verify downloads against `SHA256SUMS`.

The inherited `AirConnect-*.zip` file in this repository is an **unmodified upstream distribution**, not a binary of this fork.

## Build from Git

```sh
git clone https://github.com/thomasdye12/AirConnect-Sonos.git
cd AirConnect-Sonos
sh prepare-source.sh
```

`prepare-source.sh` fetches the pinned top-level dependencies and applies [patches/libraop-tds.patch](patches/libraop-tds.patch). It is safe to run again, upgrades the prior tds2 patch, and refuses to overwrite conflicting source changes. The modified RAOP code is distributed as a patch rather than pointing a submodule at an unpublished commit. Do not skip this step.

On Apple Silicon macOS with the Xcode command-line tools:

```sh
sh build-custom.sh
sh tests/run.sh
sh tests/run-rtsp.sh
sh tests/build-native-driver.sh
sh tests/run-pcm.sh
python3 -m unittest discover -s tests -p 'test_*.py'
```

The C control simulation needs two local IPv4 addresses. On macOS, set `NATIVE_TEST_HELPER_IP` to this Mac’s LAN address when running `test_native_control.py`; without it that one simulation is skipped. The simulated listeners never control real speakers.

On a compatible ARM hard-float Linux system with GCC, make, and binutils:

```sh
sh build-cloudkey.sh
```

The CloudKey script recompiles the changed C server/streamer objects and updates a copy of the pinned upstream RAOP archive. It avoids unrelated C++17 client code, allowing GCC 4.9 builds. Other dependencies use upstream prebuilt archives: this is **not** a full source rebuild of every third-party library. See [CUSTOM.md](CUSTOM.md) for details.

## Configure

Copy [deploy/airupnp.xml](deploy/airupnp.xml) and replace the example API URL with your own endpoint. It expects the `/zones` schema provided by [node-sonos-http-api](https://github.com/jishi/node-sonos-http-api): an array of groups containing `coordinator.uuid` and `coordinator.roomName`.

```xml
<sonos_api>http://sonos-api.local:5005/zones</sonos_api>
<sonos_cache>/var/airplay_sonos/rooms-cache.json</sonos_cache>
<sonos_name_prefix></sonos_name_prefix>
<sonos_name_suffix> (Sonos)</sonos_name_suffix>
```

When `sonos_api` is configured, its coordinator list controls which renderers are enabled and their names. Only plain local HTTP is currently supported. Without `sonos_api`, normal upstream discovery/configuration applies.

The supplied [systemd unit](deploy/airplay_sonos.service) expects the binary and configuration at `/var/airplay_sonos/airupnp-linux-arm` and `/var/airplay_sonos/Config.xml`. Adapt these paths for your host. Preserve the existing binary, configuration, and unit before replacing a working installation. The unit starts the binary directly; an old PHP/shell launcher is not needed.

## Validation and contribution

The experimental build was compiled and smoke-tested on macOS ARM64 and a Debian 8 ARM hard-float CloudKey. API validation was tested against a live Sonos HTTP API; a discovery run found 19 coordinators; basic audio playback was user-confirmed. Local sanitizer tests cover malformed API responses, metadata formatting, and RTSP artwork messages. Live artwork display failed and is explicitly recorded above.

Please report fork-specific problems in [this repository's issues](https://github.com/thomasdye12/AirConnect-Sonos/issues). Keep upstream credit and license notices when sharing modifications.

## Earlier controller and transport research (tds2)

The following records describe earlier stages. The tds3 integration above supersedes statements below about the absence of an AirPlay UDP backend.

At the tds2 stage, the production bridge used the established UPnP HTTP playback path. Independent AirPlay sessions can target separate advertised coordinators; grouped speakers share their coordinator. At that stage, the native UDP sender and audio-clip experiments were not wired into AirPlay playback.

The companion controller uses Python 3.4+ for local management:

```sh
python3 tools/airconnectctl.py status
python3 tools/airconnectctl.py rooms
sudo python3 tools/airconnectctl.py restart
# From another host, read the API without changing playback:
python3 tools/airconnectctl.py --api http://sonos-api.local:5005/zones rooms
```

`status` and `restart` operate on the local Linux systemd service. `rooms` reports the live API list, or a validated cache during an outage; it is not a check of AirPlay advertisements or audible playback. On the CloudKey, `sudo sh deploy/install-cloudkey.sh` installs the built bridge and controller at `/var/airplay_sonos/airconnectctl.py`, enables the room cache, preserves the other XML settings, and restarts the service. It creates a timestamped backup and rollback script under `/srv/airconnect-backups/` and rolls back if installation or the immediate service check fails. Verify discovery after startup; this check cannot detect later failures.

[Research guide](research/sonos-native/README.md): portable C UDP sender, packet decoder, concurrent-session tests, local WebSocket client, bounded audio-clip tests, virtual-player experiment and sanitized findings. No real Connect is required for the clip tests. They require a stopped standalone speaker, default to silence, and restore/verify its state. Run them from the full checkout on Python 3.8+ (for example, your Mac):

```sh
python3 tools/airconnectctl.py clip-test --receiver SPEAKER_IP --receiver-id SPEAKER_UUID --seconds 12 --streaming --output work/clip-test.json
```

This command never opts into audible playback. It does temporarily change mute and run a clip. Research logs contain local device information and should remain private. Audio-clip sound quality, long-duration reliability and acoustic latency are unverified. Earlier [UDP research](research/sonos-native/firmware-research/coordinator-role-followup.txt) ran two silent receivers for 90 and 150 seconds with an ordinary stopped Sonos coordinator, including stopping one while the other continued. No Connect line-in calls were needed. A synthetic coordinator still loses its receiver after roughly 76 seconds. Promoting the receiver itself kept UDP/timing alive for 120 seconds after releasing the helper, while Sonos reported paused; that long test was muted. Setup still briefly needs another speaker; trusted virtual-player registration remains unresolved. Dynamic Sonos artwork remains unsupported.

The controller also provides an experimental `udp-test` command for ordinary-group and detached receiver tests. It stays muted by default, including when sending a nonzero test signal. A [two-minute nonzero-PCM test](research/sonos-native/firmware-research/detached-pcm-followup.txt) retained the detached endpoint, still reporting paused. See the [UDP test instructions](research/sonos-native/README.md#controller-test-command-and-nonzero-pcm) for build requirements and bounded listening mode. This is a research command, not a selectable AirPlay playback backend.

Latest listening result: [Kitchen sustained a clear tone](research/sonos-native/firmware-research/kitchen-listening-test.json) for a user-confirmed 25-second test at volume 35, including roughly 16 seconds after releasing the helper. Sonos still reported paused. Initial setup still needs another speaker. The later tds3 build integrates the UDP backend with AirPlay.

Music follow-up: [Bathroom played clear music through an ending tone](research/sonos-native/firmware-research/bathroom-music-test.json) during a user-confirmed 30-second test at volume 35, with the helper released near the start. The initial music test was uncertain; the marked repeat confirmed short detached music playback. That short test preceded the tds3 AirPlay integration; long endurance remains unverified.

Shared helper: the controller can now [save a user-selected Sonos helper](research/sonos-native/README.md#configure-one-shared-setup-helper) and reuse it for detached UDP tests. Two overlapping muted streams passed setup serialization, packet/timing and restoration checks, including stopping one while the other continued. The tds3 AirPlay backend now uses this setting when native mode is enabled.
