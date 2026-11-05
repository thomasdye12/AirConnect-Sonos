# One AirPlay 2 destination per Sonos room

The optional multi-room deployment uses one Shairport Sync process per room,
one multi-client NQPTP daemon, and one native worker per active session. Existing AirPlay 1 services can remain available
as rollback; new destinations have an explicit ` (AirPlay 2)` suffix.

## Room model

- Use visible logical rooms from Sonos `GetZoneGroupState`. Satellites, surrounds
  and invisible stereo partners are not separate destinations.
- The configured physical helper stays reserved and is not advertised. Native
  sessions still require it briefly during startup.
- Sonos UUID determines the AirPlay device identity, service instance and timing
  interface. Renaming a room changes its visible name without changing identity.
- The private manifest reserves TCP ports by UUID. Retain it when regenerating;
  previously assigned ports are not reused for another room.
- Each frontend has separate timing state. Metadata is disabled for this
  deployment to avoid multiple frontends writing to the same default FIFO.
- The default speaker level is 100, with the iPhone controlling software volume.
  This is the listener-validated volume arrangement. A source at maximum volume
  can therefore request full output. Use `--speaker-volume` for a lower ceiling.

## Stereo pairs

The native worker recognises a two-member stereo room only when the invisible
partner has the same explicit `ChannelMapSet`, and both mapped members are
present. Unrelated grouped rooms are still refused. It leases the partner as
well as the main speaker, preserves the bond map, includes the partner during
coordinator promotion, and explicitly rejoins the existing partner to its own
coordinator after promotion. It does not create or remove stereo pairing.

This explicit rejoin is necessary: live testing showed the right speaker could
otherwise remain with the temporary helper. Separation is checked from the
receiver, helper and partner views before releasing the helper. Restoration
checks the original bond map and allows a bounded convergence wait.

The existing home-theatre satellites remain attached to their visible room.
Their individual acoustic channels are not independently validated by a muted
transport test. Group state can also be changed by external Sonos controllers
or automation; local leases do not lock those out.

## Generate a private plan

Save the XML string returned by `GetZoneGroupState` as `topology.xml`. Obtain
the helper UUID from the existing private helper configuration. Example:

```sh
python3 integrations/airplay2/rooms.py \
  --topology /private/path/topology.xml \
  --helper-uuid RINCON_02000000000101400 \
  --helper-config /var/airplay_sonos/native-helper.json \
  --worker /srv/airconnect-airplay2/prefix/bin/airconnect-ap2-worker \
  --local-ip 192.0.2.10 --capacity 32 \
  --output /private/path/rooms
```

Without `--write`, this only prints a plan. With `--write`, it writes private
per-room configs and `manifest.json`. The capacity argument is an explicit
operator assertion about the installed daemon, not a way to change capacity.
Validate description URLs against device UDNs and check for occupied TCP ports
before starting services. Generated configs contain household addresses and
identities and must stay outside the public repository.

## Timing capacity and deployment

For the pinned NQPTP source described in README.md:

```sh
python3 integrations/airplay2/expand-timing.py /absolute/path/nqptp
make -C /absolute/path/nqptp
```

The change increases `MAX_CLIENTS` from 16 to 32. Per-client clock tables already
exist in the pinned revision; the shared-memory version stays 11 and the
frontend does not need an ABI rebuild. Keep upstream source and GPLv2 notices.
Archive both previous binaries and the exact modified source when deploying.
NQPTP retains client slots for names until restart, so do not manufacture new
timing names on each service restart.

For the existing `/srv/airconnect-airplay2` Linux installation, install the
verified binaries under `prefix/bin`, generated room files under `rooms`, and
keep the installer alongside `airconnect-ap2@.service`. In a maintenance window,
stop the old single-room test services and the timing daemon, install the new
timing daemon atomically, then start timing. Confirm it can allocate a distinct
version-11 shared-memory region for every planned room, including rooms above
the old 16-client boundary.

```sh
python3 integrations/airplay2/install-rooms.py          # plan only
python3 integrations/airplay2/install-rooms.py --apply --enable
```

The installer uses the private manifest at `/srv/airconnect-airplay2/rooms`,
installs a systemd template/target, restarts desired room services, and stops
removed instances from its previous installed-unit record. `--enable` makes
the room target start at boot. Applying interrupts current streams and invokes
their restoration path. It does not disable the existing production bridge.
All native services must share the same user and `/tmp` lease directory; do not
add `PrivateTmp` to these units.

## Verification and operation

Check every unit is active, every service port answers RTSP OPTIONS, and all
planned AirPlay names resolve with the expected unique IDs and ports. Test
independent streams and stopping one while another continues. For clock
isolation, compare timing shared-memory regions across different room names.
Audible synchronization of a group selected on one iPhone needs a separate
listening/measurement test; advertising multiple receivers does not prove it.

Helpers prepare receivers sequentially under a bounded lease wait. Selecting
many rooms simultaneously can exceed startup deadlines; 18 advertised rooms
does not promise 18 simultaneous decoded streams on an old ARM host. Measure
CPU/memory under the intended active load. Rooms must be stopped and independent
of unrelated Sonos groups before opening a native session; existing activity is
not forcibly taken over.

```sh
systemctl status airconnect-ap2-rooms.target
systemctl status 'airconnect-ap2@*.service'
journalctl -u airconnect-ap2@ROOM_KEY --since '10 minutes ago' -o cat --no-pager
```

Analyse a saved unit log with `diagnose.py`. Keep raw logs private. Update the
topology and regenerate configurations deliberately after address/name changes;
this deployment does not run an automatic discovery/reconfiguration daemon.

To roll back, stop and disable `airconnect-ap2-rooms.target` (its instances have
`PartOf`), restore saved worker/timing binaries while timing is stopped, then
start timing and the previous single-room receiver if wanted. The original
AirPlay 1 installation remains available. Verify any active speaker restoration.
