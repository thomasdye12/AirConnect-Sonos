# Operation and troubleshooting

Install using [INSTALL.md](INSTALL.md). The commands below assume the supplied Linux paths. Run privileged commands with `sudo`, or omit it when already root. A service being active or a packet counter increasing is not proof that a speaker is producing sound.

## Everyday commands

```sh
python3 /var/airplay_sonos/airconnectctl.py status
python3 /var/airplay_sonos/airconnectctl.py rooms
python3 /var/airplay_sonos/airconnectctl.py helper-show
sudo systemctl status airplay_sonos.service --no-pager
sudo systemctl status airconnect-dashboard.service --no-pager
sudo systemctl status airconnect-intercom.service --no-pager
```

Only query optional services you installed. The dashboard defaults to `http://BRIDGE_LAN_IP:8088`. It is read-only and unauthenticated; keep it on a trusted LAN. Service/ownership views refresh approximately every five seconds, room/API views every fifteen seconds, with stale indicators when a refresh fails.

Restart AirPlay after changing room names/groups, XML settings or the helper:

```sh
sudo python3 /var/airplay_sonos/airconnectctl.py restart
```

Reconnect the iPhone after a restart. Restarting interrupts active sessions. Changing dashboard settings only requires restarting `airconnect-dashboard.service`; changing intercom settings requires restarting `airconnect-intercom.service`. Do not restart all components as a first diagnostic step: collect the failure while it is still visible.

## Logs and session evidence

```sh
sudo tail -n 100 /var/log/airupnp.log
sudo tail -n 100 /var/log/airconnect-intercom.log
sudo journalctl -u airconnect-intercom.service -n 100 --no-pager
sudo python3 -m json.tool /run/airconnect-intercom/status.json
```

Intercom status contains current sessions and the last ten completed sessions from this service process. Restarting clears that history. Look for `state`, `error`, `exit_code`, `received_bytes`, `output_frames`, `queued_frames`, `silence_frames`, `dropped_frames` and `recoveries`. Counters may be absent before a worker has reported them. A zero exit and no error indicate clean worker completion; they do not prove the user chose to stop or that all audio was audible.

For Protect, inspect the application's existing stdout/stderr logs for `[protect-talkback]`. The sequence should include client connection, camera endpoint lookup, bridge/camera connection, speaker readiness, client readiness, first microphone bytes and first decoded PCM. Closure events include byte counts and WebSocket close codes. Code `1001` means the client went away; it does not distinguish a deliberate button press from app/background/network behavior. Runtime bridge failures are reported separately.

The AirPlay example caps its log at 5 MB. Include the intercom log in your host's log-rotation policy. Dashboard diagnostics and logs can contain household names, IP addresses and device identities; redact them before opening an issue. Never share the bearer key or private configuration.

## Symptoms and next checks

| Symptom | Check and action |
| --- | --- |
| No AirPlay destinations | Check service/logs, API reachability and `/zones` data, enabled settings, mDNS/SSDP forwarding and unicast routes. The example enables API coordinators; its common default is disabled. |
| Old room names or membership | Restart AirPlay after the API reflects the change. Intercom's explicit room list must be edited separately. |
| API outage prevents startup | A configured valid cache can be used for up to 24 hours and is bound to the API URL. Without one, startup fails and systemd retries after 30 seconds. Fix the API rather than removing validation. |
| Native setup refused as busy | Stop and ungroup both devices in the Sonos app. Paused is not stopped. Check the dashboard for another session's actual lease; do not delete lock files to bypass ownership. |
| Helper configuration rejected | Run `helper-show`; verify TCP 1400 reachability and re-run `helper-set --address HELPER_IP` after an IP change. Use a different receiver from the helper. |
| Group setup or restoration failed | Read the named setup stage and each device's own topology. Wait for the current operation to finish. Inspect the Sonos app before retrying; a successful control reply alone does not establish membership. |
| Intercom HTTP 401/403 or socket rejection | Check bearer key matches, `allowed_clients` includes the actual source IP, correct LAN bind/port, and no browser Origin header. Do not put the secret in a URL. |
| WebSocket connects but no sound | Wait for `ready`; inspect first microphone/decoded PCM events. Confirm ADTS AAC at Protect ingress, FFmpeg path and room mapping. Check mute/volume and rising bytes; then arrange an audible check. |
| Connection closes around setup | Correlate client, camera endpoint and bridge events. A client disconnect during lookup now cancels setup. Do not treat a transient app warning as proof the bridge failed. |
| `PCM input congested`, native timeout or dropouts | Preserve the underlying native error and counters. Inspect host CPU/load, network and decoder backpressure. Current intercom tolerates bounded short stalls, not sustained overload. More buffering is not a general fix. |
| UDP flowing but speaker reports paused | This was observed during working listening tests. Check actual sound and native clock/packet evidence; Sonos transport state alone is inconclusive. |
| Audio/video offset | Calibrate `native_sync_offset_ms` with the same source and receiver, then reconnect. Positive delays audio. Keep startup, steady-state sync and pause tail measurements separate. |
| Audio continues after pause | Check when the source sends FLUSH/TEARDOWN. Current FLUSH clears input while preserving silence. A larger sync offset does not solve delayed source control. |
| Distortion on older build | Verify current source/tds4 continuity fix is installed. If current, capture timing/drop/realignment counters and compare the same source; do not assume a quiet transport log proves audio quality. |
| Missing artwork or title | Dynamic artwork is not working; native title/artwork is not implemented. This is a limitation, not an installation fault. |

## Upgrades and rollback

Record the running commit/release, compiler target, configuration and service state before upgrading. Keep backups private because they contain household configuration and keys. Wait for sessions to finish; native cleanup should run before replacing executables.

- **AirPlay:** use the existing-installation procedure in [INSTALL.md](INSTALL.md#upgrading-an-existing-installation). `install-cloudkey.sh` backs up the old binary, XML and controller under `/srv/airconnect-backups/` and prints its rollback path. It does not install a new service unit or update other components. Review/run the generated rollback for that specific backup if needed.
- **Dashboard:** use `deploy/install-dashboard.sh`; its backup includes files, environment, unit and previous enabled/active state. Its generated rollback affects the dashboard only.
- **Intercom:** stop `airconnect-intercom.service`, privately back up its directory and unit, replace the built worker/Python script (and unit if changed), run `systemctl daemon-reload` if the unit changed, then start it. Preserve the existing credential and room/helper configuration. Restore that backup to roll back.
- **Protect adapter:** back up the module/config before applying the integration patch. Set `enabled` to false and restart Protect to select its existing HTTP Sonos route. Native failure does not automatically start a competing HTTP session.

To disable native AirPlay, use `native-mode --enabled 0` and restart; existing per-device overrides survive, so inspect those too. To stop intercom, stop its service and allow graceful restoration. Do not force-kill workers as routine cleanup.

## Reporting a failure

Include the component, commit/release, OS/architecture, room model, rough time, how long setup/playback lasted, and whether the client closed itself or reported an error. Include redacted logs from both Protect and the bridge, the final session counters, and whether speaker restoration succeeded. State whether the test was muted, heard by a listener, or measured acoustically. This makes an app disconnect distinguishable from a decoder, native transport or speaker failure.
