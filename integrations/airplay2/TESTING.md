# Testing music from an iPhone

Use a separately named experimental destination. A running receiver or a stream
of packets is not evidence of audible playback. Retain the previous worker binary
and the existing AirPlay frontend during testing.

## Before testing

- Build the worker from current source, including the native clock-fraction and
  32-bit packet-counter corrections. `bin/airconnect-ap2-worker --version` reports
  its build without contacting speakers. Source-only builds can set
  `AP2_SOURCE_REVISION` to the revision/label of the exact uploaded source.
- Run the timeline/backend tests and native packet/sender tests. Run the simulated
  lifecycle checks described in the integration README. Verify a muted live
  session and restoration on the intended host before an audible attempt.
- Use the same host/user/lease directory as other native senders. The receiver
  and helper must be stopped and standalone; do not bypass the busy checks.
- Verify that the test config points to the rebuilt worker, uses a unique
  endpoint name/port/timing interface, and has the intended mute/volume settings.
  The example intentionally starts muted.

## First listening test

1. Select the destination marked **AirPlay 2 Test** in the music app's AirPlay
   picker. Start a familiar track and set the iPhone's AirPlay volume around
   halfway. Allow up to about ten seconds for helper-assisted startup.
2. Listen for 30 seconds. Record whether sound is present, clean, and at a normal
   level. If silent, leave it connected for 15 seconds to obtain diagnostic
   windows; avoid turning the speaker volume up repeatedly.
3. Lock the phone and reopen it. Switch to a non-audio app, then test another app
   with sound and, if wanted, a call. Record whether music continues, pauses or
   gets replaced, and where the other app's audio plays. Record the source app
   and iOS version. Receiving AirPlay 2 does not dictate every source app's
   routing/interruptions policy.
4. Test pause/resume, seek, volume and disconnect/reconnect. Finally, play for at
   least ten minutes to cross the previous native six-minute counter boundary.
5. Disconnect AirPlay and verify the target and helper are restored. A worker
   exit code alone does not prove restoration; inspect `native restore ...:
   verified` for the relevant devices, and check actual speaker state if needed.

## Diagnostics

Export a fresh test interval from the experimental service's journal (replace
the example unit with the deployed one):

```sh
journalctl -u airconnect-ap2@ROOM_KEY --since '10 minutes ago' --no-pager -o cat > /private/path/ap2-session.log
python3 integrations/airplay2/diagnose.py /private/path/ap2-session.log
python3 integrations/airplay2/diagnose.py --json /private/path/ap2-session.log
```

The analyser runs with Python 3.4 or later and also accepts stdin. It reports the
latest recorded session, not whether a service is currently alive. Keep raw logs
private: frontend logs can contain household and source identities.

| Finding | Interpretation / next check |
| --- | --- |
| No PCM evidence | Verify destination selection, source playback and frontend setup; wait for a five-second worker report. |
| Levels unavailable | Old/truncated log; capture the updated worker. |
| Input near silent | Maximum input sample magnitude is at most 32/32768, approximately -60 dBFS. Check the source track and software volume; dither is not music. |
| Output near silent | Input has stronger signal but rendered output does not. Check deadline placement, late frames and flush behavior. |
| PCM signal present | Nontrivial signal was submitted to the native sender. Actual speaker sound, native timing and speaker state still need checking. |
| Worker/restoration failed | Inspect the private failure log and verify speaker state before retrying. |

Five-second `ap2 PCM` records give cumulative frame counters and window peaks.
`ap2 worker closed` records include whole-session peaks, including short sessions.
The silence counter includes intentional startup/pause silence; it is not an
audio-loss percentage. Peak amplitude is a diagnostic hint, not a loudness meter
or proof of audible sound. A muted session may correctly report signal present.

## Rollback

When idle, stop only the experimental frontend, restore its saved worker binary
or config path, then start that frontend again. Leave the production receiver and
shared timing daemon alone unless their own maintenance requires a change. Do
not replace a running executable in place: install to a temporary path and rename
it, allowing any existing worker to finish and restore its speaker.
