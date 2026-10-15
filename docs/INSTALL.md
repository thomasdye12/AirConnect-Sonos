# Install AirConnect-Sonos

This guide covers the tested ARMv7 hard-float Linux/systemd deployment. Use it in order for a fresh installation. Existing installations should use [the upgrade section](#upgrading-an-existing-installation). Dashboard and intercom are optional services; neither is required for basic AirPlay audio.

The IP addresses below are documentation placeholders. Replace them with addresses on your LAN. Run build commands as your normal account and installation commands with `sudo`; omit `sudo` if already root.

## 1. Prepare the host and network

You need Git, a compatible C/C++ compiler, make, binutils and Python 3.4 or newer. The old CloudKey build was tested with GCC 4.9. On a compatible Debian-based host, the package names are typically:

```sh
sudo apt-get install git gcc g++ make binutils python3 curl
```

The scripts use pinned upstream dependency archives and rebuild the modified code. They do not rebuild every third-party dependency. Do not assume another distribution or architecture is binary-compatible. Prefer wired networking and stable/DHCP-reserved addresses for the bridge, helper and receivers.

For automatic room names, have a working [node-sonos-http-api](https://github.com/jishi/node-sonos-http-api) instance or compatible `/zones` endpoint. This project consumes that API; it does not install or host it. Verify that the bridge can reach it:

```sh
curl --fail http://SONOS_API_HOST:5005/zones
```

The response must be a nonempty array of groups with `coordinator.uuid` and `coordinator.roomName`. Room/group membership is loaded at bridge startup, not continuously.

Allow these paths within your trusted LAN:

| Traffic | Purpose |
| --- | --- |
| mDNS UDP 5353 and UPnP/SSDP UDP 1900 | Discovery; routed VLANs need suitable discovery forwarding and unicast routing. |
| iPhone → bridge advertised AirPlay TCP/UDP ports | AirPlay control and audio. Ports depend on bridge configuration. |
| Bridge → speaker TCP 1400 | Description, topology and SOAP control. |
| Bridge → receiver UDP 7020; receiver → bridge allocated UDP clock port | Native audio and timing. The clock listener uses an ephemeral port. |
| Speaker → bridge's advertised HTTP port | Original HTTP audio path and hosted artwork. |
| Bridge → Sonos API TCP 5005, or your chosen API port | Room naming. |
| Browser → bridge TCP 8088, optional | Read-only dashboard; no authentication. |
| Approved intercom host → bridge TCP 8089, optional | Authenticated PCM WebSocket and status API. |

Do not forward the dashboard or intercom ports from the internet. The intercom listener checks a bearer token and source IP but plain `ws://` does not encrypt them. This project does not install VLAN relays, firewall rules or TLS termination.

## 2. Fetch and build current source

```sh
git clone --branch sonos-improvements https://github.com/thomasdye12/AirConnect-Sonos.git
cd AirConnect-Sonos
sh prepare-source.sh
sh build-cloudkey.sh
# Optional, but needed for microphone/intercom input:
sh build-intercom.sh
```

Outputs are `bin/airupnp-linux-arm`, its static variant, and `bin/airconnect-intercom-worker`. Prefer the regular AirPlay binary on the tested host. Preparation is repeatable and refuses conflicting RAOP edits. The modified `common/libraop` working tree is intentional.

For Apple Silicon development instead:

```sh
sh build-custom.sh
HOST=macos PLATFORM=arm64 CC=clang sh build-intercom.sh
```

The macOS commands build code; they do not install Linux services. See [build and test details](../CUSTOM.md). For other targets, matching `HOST`, `PLATFORM`, compiler and dependency archives are required; no universal build is promised.

The [tds4 release](https://github.com/thomasdye12/AirConnect-Sonos/releases/tag/v1.12.4-tds4) has older ARM AirPlay binaries, a controller and `SHA256SUMS`. Verify those assets against that checksum file if using them. They lack the later intercom/recovery work. The inherited `AirConnect-*.zip` in Git is an unmodified upstream distribution, not this fork's build.

## 3. Install a fresh AirPlay service

Run from the checkout on the bridge. This block refuses to overwrite an existing installation:

```sh
sudo sh <<'SH'
set -eu
app=/var/airplay_sonos
test ! -e "$app/Config.xml"
test ! -e /etc/systemd/system/airplay_sonos.service
install -d -m 755 "$app"
install -m 755 bin/airupnp-linux-arm "$app/airupnp-linux-arm"
install -m 755 tools/airconnectctl.py "$app/airconnectctl.py"
install -m 644 deploy/airupnp.xml "$app/Config.xml"
install -m 644 deploy/airplay_sonos.service /etc/systemd/system/airplay_sonos.service
SH
```

Edit the configuration before starting:

```sh
sudoedit /var/airplay_sonos/Config.xml
```

At minimum, replace `sonos_api` with your reachable API URL. The example config uses HTTP output and conservative HTTP buffering:

```xml
<sonos_api>http://SONOS_API_HOST:5005/zones</sonos_api>
<sonos_cache>/var/airplay_sonos/rooms-cache.json</sonos_cache>
<sonos_name_prefix></sonos_name_prefix>
<sonos_name_suffix> (Sonos)</sonos_name_suffix>
```

Keep these at the XML root, as in [the supplied example](../deploy/airupnp.xml). That example has `<common><enabled>0</enabled></common>` because the API enables its selected coordinators. If using upstream discovery without an API, also configure enabled devices/defaults appropriately; simply removing the API from this example will not enable every device.

Start and inspect:

```sh
sudo systemctl daemon-reload
sudo systemctl enable airplay_sonos.service
sudo systemctl start airplay_sonos.service
python3 /var/airplay_sonos/airconnectctl.py status
python3 /var/airplay_sonos/airconnectctl.py rooms
sudo tail -n 60 /var/log/airupnp.log
```

The supplied unit launches the binary directly with `-Z`. Disable any previous shell/PHP launcher or duplicate service for the same bridge before starting this one. There is no need for the old room-naming script. Select an advertised room in AirPlay and test at a comfortable speaker volume. An active service is not by itself a playback test.

## 4. Enable native Sonos UDP, optionally

Choose a real Sonos device to serve as the helper. Stop it and remove it from any group in the Sonos app. The target receiver must also be stopped and standalone. A paused source does not meet the current `STOPPED` precondition. Keep the helper available rather than using it for normal playback during setup.

```sh
sudo python3 /var/airplay_sonos/airconnectctl.py helper-set --address HELPER_IP
python3 /var/airplay_sonos/airconnectctl.py helper-show
sudo python3 /var/airplay_sonos/airconnectctl.py native-mode --enabled 1
sudo python3 /var/airplay_sonos/airconnectctl.py restart
```

`helper-set` reads the actual speaker description and saves its name, address and UUID. It does not pair a virtual device or use the helper's line-in. The default path is `/var/airplay_sonos/native-helper.json`. Enabling common native mode excludes the helper from AirPlay destinations. Update the helper configuration after an address change and restart the bridge.

For a muted setup check, use `native-mode --enabled 1 --muted`, restart, and inspect the logs. To listen afterwards, run the command again without `--muted` and restart. For rollback to the original HTTP default:

```sh
sudo python3 /var/airplay_sonos/airconnectctl.py native-mode --enabled 0
sudo python3 /var/airplay_sonos/airconnectctl.py restart
```

Existing per-device overrides survive these commands. To keep a particular grouped room on HTTP, merge `<native_udp>0</native_udp>` into its existing `<device>` entry. Do not create duplicate entries for the same UDN. A device UDN has the form `uuid:RINCON_...`; intercom room UUIDs omit the `uuid:` prefix.

The public `1000:2000` latency setting is the conservative HTTP profile. Native integration tests used `500:0`; treat that as a tested starting point, not a guarantee. A/V calibration is separate:

```sh
sudo python3 /var/airplay_sonos/airconnectctl.py native-mode --enabled 1 --sync-offset-ms 0
sudo python3 /var/airplay_sonos/airconnectctl.py restart
```

Positive offsets delay audio; negative offsets advance its local presentation. Range: -1000 to 5000 ms. Omitting the option preserves the saved value. Put `native_sync_offset_ms` in a device entry for a room-specific override. Reconnect AirPlay after restarting. Do not use this offset to try to remove an intercom setup delay or an AirPlay pause tail.

## 5. Install the optional dashboard

From the checkout on the bridge:

```sh
sudo sh deploy/install-dashboard.sh BRIDGE_LAN_IPV4 8088
```

Open `http://BRIDGE_LAN_IPV4:8088`. This separate installer backs up an existing dashboard, enables `airconnect-dashboard.service` and prints a rollback script. It does not restart audio. Change `/etc/default/airconnect-dashboard` to alter its bind address/port, then restart only the dashboard service.

It is a read-only LAN monitor, not a control panel: it cannot change volume, start playback, edit configuration or run shell commands. Diagnostics include room names, addresses and logs; review them before sharing.

## 6. Install the optional intercom

Follow [the intercom guide](../integrations/unifi-protect/README.md#bridge-installation). It includes the separate worker/service installation, credential creation, room configuration, Protect adapter, a muted test and the generic WebSocket protocol. Intercom does not require an active AirPlay connection, but it needs the same configured real helper.

If running HTTP AirPlay alongside intercom, reserve the helper yourself: it is automatically hidden only when native mode is enabled for it/common settings. Intercom and native AirPlay share ownership locks on this host; the legacy HTTP path and unrelated third-party controllers do not participate in those locks.

## Upgrading an existing installation

Check for local edits before pulling. Do not reset the patched RAOP submodule:

```sh
git status --short
git pull --ff-only origin sonos-improvements
sh prepare-source.sh
sh build-cloudkey.sh
sh build-intercom.sh
```

For the established CloudKey installation only:

```sh
sudo sh deploy/install-cloudkey.sh
```

This is an **upgrade script**, not a fresh installer: it expects the old binary, `Config.xml` and systemd unit to exist. It backs them up under `/srv/airconnect-backups/`, installs the bridge/controller, enables the room cache, preserves other XML settings, and restarts/checks AirPlay. It does not replace the systemd unit, install intercom or upgrade the dashboard. Its rollback restores the bridge/config/controller; service-unit changes you make separately need separate restoration.

Upgrade the dashboard with its own installer. Upgrade intercom by stopping its service, backing up its installed worker/script/config/key/unit privately, replacing the worker and Python script, then starting it again. Preserve the token and room configuration. Wait for active intercom sessions to finish first. See [component rollback](OPERATIONS.md#upgrades-and-rollback).
