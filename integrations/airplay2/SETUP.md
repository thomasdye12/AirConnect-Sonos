# Optional AirPlay 2 setup on Linux

This experimental integration adds an AirPlay 2 destination for each configured
Sonos room. It runs on the bridge host and does not install firmware on speakers.
It is separate from the normal AirConnect installer and released binaries.

## Requirements and current limits

- A Linux host with systemd and Avahi, on a network where the phone can discover
  the bridge and the bridge can reach the speakers. Use stable IPv4 addresses.
- A working native Sonos setup and a dedicated physical helper, configured as
  described in [native output setup](../../docs/INSTALL.md#4-enable-native-sonos-udp-optionally).
  The helper is reserved
  for preparing sessions and is excluded from AirPlay destinations.
- A compiler, Python 3, Autotools, pkg-config, and the dependencies described in
  [build notes](BUILD-NOTES.md) and the pinned upstream projects. The native worker
  needs dependency archives matching the host architecture and C library.
- Receivers and helper must be stopped; receivers cannot belong to unrelated
  Sonos groups. Existing two-speaker stereo pairs are handled as one room.

Single-room iPhone listening has been confirmed. Eighteen receiver identities
were tested for discovery/control, with muted stereo-pair and two-worker
concurrency checks. This does **not** establish synchronized multi-room audio,
18 simultaneous music streams, all-model compatibility, or long-term stability.
See [validation.json](validation.json) for evidence and remaining failures.

## 1. Get and build the source

```sh
git clone --branch airplay2-experimental https://github.com/thomasdye12/AirConnect-Sonos.git
cd AirConnect-Sonos
sh prepare-source.sh
```

Follow the [pinned build commands](README.md#build-only) to build Shairport Sync
with the AirConnect adapter, NQPTP, and the native worker. The frontend build
script modifies only your supplied Shairport checkout. For the tested ARMv7
Linux worker, set `HOST=linux PLATFORM=arm CC=gcc`; the default is macOS ARM64.
Other Linux architectures need matching dependency archives, not that ARM flag.

Before building NQPTP, expand its fixed client table if you need more than 16
room receivers:

```sh
python3 integrations/airplay2/expand-timing.py /absolute/path/nqptp
(cd /absolute/path/nqptp && autoreconf -fi && ./configure && make)
```

This raises capacity to 32 registered receivers, including idle ones. It is a
software table limit, not a protocol limit or a simultaneous-playback guarantee.
Run the [offline tests](README.md#tests-and-failure-behavior) before installation.

## 2. Install the three executables

The supplied systemd files use a fixed layout. On a new installation:

```sh
sudo install -d -m 755 /srv/airconnect-airplay2/prefix/bin
sudo install -m 755 /absolute/path/shairport-sync/shairport-sync /srv/airconnect-airplay2/prefix/bin/
sudo install -m 755 /absolute/path/nqptp/nqptp /srv/airconnect-airplay2/prefix/bin/
sudo install -m 755 bin/airconnect-ap2-worker /srv/airconnect-airplay2/prefix/bin/
```

Install required runtime libraries too. The service files search the normal
system locations and `/srv/airconnect-airplay2/prefix/lib`; copying executables
alone does not copy dependencies. Use `ldd` on each executable to check for
missing libraries. For upgrades, stop room services first, back up binaries and
configuration, and replace executables atomically while idle.

Install the supplied timing unit, then start it:

```sh
sudo install -m 644 integrations/airplay2/airconnect-ap2-timing.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start avahi-daemon.service airconnect-ap2-timing.service
```

Use one matched NQPTP instance. Resolve any existing timing service/UDP port
conflict before starting this one; do not stop a daemon used by other receivers
without accounting for those receivers. These units run as root, including for
PTP ports, and share `/tmp` ownership leases with other native senders. Do not add
`PrivateTmp` or run a second uncoordinated bridge against the same speakers.

## 3. Configure one room, then expand

Start with the [single-room example](airconnect.conf.example), replacing every
example identity, path and address with your private configuration. It starts
muted. Follow [the listening checklist](TESTING.md) to verify transport,
restoration, and then audible playback at a moderate phone volume.

For multiple rooms, export the XML returned by Sonos `GetZoneGroupState` and use
[the room generator](MULTIROOM.md#generate-a-private-plan). Generate into
`/srv/airconnect-airplay2/rooms` using `--write`, with the actual bridge IP,
helper UUID, helper config path and installed timing capacity. Keep the manifest
for subsequent regeneration so identities and port reservations stay stable.
The generator does not discover speakers or validate their live availability.

Review the generated plan and verify device identities and available ports.
From this checkout, run:

```sh
sudo python3 integrations/airplay2/install-rooms.py
sudo python3 integrations/airplay2/install-rooms.py --apply --enable
```

The first command only prints a plan. The second installs room units, starts or
restarts them, and enables the room target at boot. Timing is started through
the room units' dependency. Applying changes interrupts current streams.
Generated room configs use speaker level 100 with phone software volume;
`rooms.py --speaker-volume` can set a lower ceiling.

Choose **Room (AirPlay 2)** in your music app. Startup uses the helper briefly,
so allow several seconds. Confirm disconnect restores the speaker state before
trying additional rooms. Background audio routing depends on the source app;
AirPlay 2 support alone does not guarantee every phone sound stays local.

## Operation and removal

See [operation and rollback](MULTIROOM.md#verification-and-operation) for logs,
configuration regeneration and testing. To disable this optional deployment:

```sh
sudo systemctl disable --now airconnect-ap2-rooms.target
sudo systemctl stop airconnect-ap2-timing.service
```

Only stop timing if it is dedicated to these receivers. Verify speaker
restoration. The normal AirPlay service is not removed by this installation.
Keep credentials, topology exports, generated configs, logs and pairing state
out of Git. Redistributing built components also requires preserving their
respective source and license obligations; see [attribution](README.md#attribution).
