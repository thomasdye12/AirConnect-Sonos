# AirConnect-Sonos

A modified fork of **[Philippe's AirConnect](https://github.com/philippe44/AirConnect)**, maintained by [Thomas Dye](https://github.com/thomasdye12), with native Sonos HTTP API room naming and improvements to the AirUPnP metadata handling and service configuration.

**This is a copy of and derivative work based on AirConnect, not an independently created AirPlay implementation.** The original bridge, discovery, codecs, and protocol work belong to their respective upstream authors. This fork is not an official AirConnect, Sonos, or Apple release.

Based on AirConnect v1.12.4 at [`5fdb61e`](https://github.com/philippe44/AirConnect/commit/5fdb61e20de59bac5dbda9f6e2ed56ce549ccabd). The original documentation is preserved in [README.upstream.md](README.upstream.md). See [NOTICE.md](NOTICE.md) and the original [LICENSE](LICENSE) for attribution and dependency licensing.

## What this fork changes

- **Native room naming from a Sonos HTTP API:** reads `/zones` directly, publishes group coordinators, and applies configurable name prefixes/suffixes such as `Kitchen (Sonos)`. No PHP configuration-generation script is required.
- **Validated startup room list:** rejects invalid, duplicate, empty, or oversized API responses. With the supplied systemd unit, failed starts retry after 30 seconds.
- **Sender fallback:** uses the name in the AirPlay request when available, otherwise the sender IP. Discovery-based friendly iPhone names are **not implemented yet**.
- **Metadata handling:** bounded ICY fields, safe handling of missing fields, retained metadata across HTTP reconnects, and safe text insertion in initial UPnP metadata.
- **Experimental artwork reception:** accepts JPEG/PNG sent by the AirPlay source and serves the current image for the session instead of expiring it after two minutes. Image updates get distinct URLs.
- **Direct systemd startup:** uses `-Z` for non-interactive operation, avoiding the original local shell/PHP launcher and its observed excessive CPU usage. Logging is capped at 5 MB.

## Important limitations

**Changing artwork in the Sonos app does not work in this version.** Receiving/hosting an image is not proof that Sonos displays it. The current MP3/AAC ICY path sends artwork as `StreamURL`; Sonos documents that its ICY parser reads only `StreamTitle`. Its documented dynamic-artwork route is HLS/ID3 metadata, which this fork does not implement. See [Sonos's audio-format documentation](https://docs.sonos.com/docs/supported-audio-formats).

Basic audio playback and API room naming were verified on a first-generation UniFi CloudKey. Automated tests verify metadata handling, but end-to-end Sonos title/artist updates are not fully validated. The room list is a **startup snapshot**: restart after API room/group changes. There is no offline persistent room cache.

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

`prepare-source.sh` fetches the pinned top-level dependencies and applies [patches/libraop-tds.patch](patches/libraop-tds.patch). It is safe to run again and refuses to overwrite conflicting source changes. The modified RAOP code is distributed as a patch rather than pointing a submodule at an unpublished commit. Do not skip this step.

On Apple Silicon macOS with the Xcode command-line tools:

```sh
sh build-custom.sh
sh tests/run.sh
sh tests/run-rtsp.sh
```

On a compatible ARM hard-float Linux system with GCC, make, and binutils:

```sh
sh build-cloudkey.sh
```

The CloudKey script recompiles the changed C server/streamer objects and updates a copy of the pinned upstream RAOP archive. It avoids unrelated C++17 client code, allowing GCC 4.9 builds. Other dependencies use upstream prebuilt archives: this is **not** a full source rebuild of every third-party library. See [CUSTOM.md](CUSTOM.md) for details.

## Configure

Copy [deploy/airupnp.xml](deploy/airupnp.xml) and replace the example API URL with your own endpoint. It expects the `/zones` schema provided by [node-sonos-http-api](https://github.com/jishi/node-sonos-http-api): an array of groups containing `coordinator.uuid` and `coordinator.roomName`.

```xml
<sonos_api>http://sonos-api.local:5005/zones</sonos_api>
<sonos_name_prefix></sonos_name_prefix>
<sonos_name_suffix> (Sonos)</sonos_name_suffix>
```

When `sonos_api` is configured, its coordinator list controls which renderers are enabled and their names. Only plain local HTTP is currently supported. Without `sonos_api`, normal upstream discovery/configuration applies.

The supplied [systemd unit](deploy/airplay_sonos.service) expects the binary and configuration at `/var/airplay_sonos/airupnp-linux-arm` and `/var/airplay_sonos/Config.xml`. Adapt these paths for your host. Preserve the existing binary, configuration, and unit before replacing a working installation. The unit starts the binary directly; an old PHP/shell launcher is not needed.

## Validation and contribution

The experimental build was compiled and smoke-tested on macOS ARM64 and a Debian 8 ARM hard-float CloudKey. API validation was tested against a live Sonos HTTP API; a discovery run found 19 coordinators; basic audio playback was user-confirmed. Local sanitizer tests cover malformed API responses, metadata formatting, and RTSP artwork messages. Live artwork display failed and is explicitly recorded above.

Please report fork-specific problems in [this repository's issues](https://github.com/thomasdye12/AirConnect-Sonos/issues). Keep upstream credit and license notices when sharing modifications.
