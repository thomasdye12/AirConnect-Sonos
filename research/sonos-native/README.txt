HISTORICAL NOTES: see README.md for the current status and safe entry points.
Production AirConnect was updated separately in tds2; these transport tools remain experimental.

Sonos native line-in investigation — 14 October 2026

Latest follow-up: native UDP setup without the Connect remains unresolved.
A separate experimental HTTP audioClip input passed silent finite/open-ended
stream tests and concurrent independent-room tests. It is not an AirPlay backend;
audible quality and latency are unverified. See firmware-research/streaming-input-tests.txt
and clip_stream_probe.py. The production bridge remains unchanged.

Status update: audible native UDP tone playback has now been demonstrated on
the Play:3 using the group-member route. See firmware-research/native-playback-result.txt.
The user also confirmed clear music via the Python prototype. A portable C
packetizer, paced sender and timing service are now implemented and tested.
A standalone virtual Sonos device and AirPlay integration are not yet working. Nothing has been installed into AirConnect,
and the working CloudKey service has not been changed.

Implemented
- native/: portable C packetizer and paced UDP/timing engine; see native/INTEGRATION.txt.
- native_sender.py: ctypes harness for C-engine live tests.
- linein.py: classic Ethernet pcap reader, VLAN support, IPv4 UDP extraction,
  strict observed-format decoder and encoder, segment detection and WAV export.
- transport.py: observed Sonos clock representation and response framing;
  paced packet generation/sending from 44.1 kHz stereo signed 16-bit LE PCM.
- soap.py: small SOAP client used for the bounded live investigations.
- probe.py: muted transport-settings probe with source/state/mute restoration.
- discovery_probe.py: temporary synthetic line-in advertisement and setup probe.
  This is a minimal research stub, not a full Sonos device emulator. It does not
  implement event notifications, household membership, authenticated device
  control, retransmission or packet-recovery services. Do not treat its failure
  as proof that a more complete emulator is impossible.
- test_linein.py: nine tests, including a real UDP loopback sender/receiver.

Offline results
13,826 audio packets decoded and re-encoded byte-for-byte.
674 omitted trailing zero bytes reconstructed across 670 shorter packets.
No sequence discontinuities and no audio-byte-position gaps within either run.
Timestamps agree with 251 stereo sample frames at 44100 Hz, within 0.61 us per
packet step. Most packets contain a 28-byte header and 1004 PCM bytes.
Recovered audio: decoded/segment-01.wav (28.993 s), segment-02.wav (49.699 s).
A listening check remains useful; no acoustic latency measurement was made.
The stop/restart gap is not a latency measurement.

Tests
Run from this directory:
  python3 -m unittest -v test_linein.py
The UDP loopback test needs permission to bind local sockets.
All nine tests passed on the Mac. All Python modules also pass py_compile.

Decode another matching capture
  python3 linein.py CAPTURE.pcap --output decoded --source SOURCE_IP --destination RECEIVER_IP
The parser intentionally rejects unsupported formats and fragmented IP packets.
Only one firmware/format/capture combination has been validated.

Observed packet layout (offsets within UDP payload)
  0..1    00 02, meaning not established
  2..3    Big-endian 16-bit sequence counter, wraps at 65535
  4..7    03 00 00 00 for observed audio packets; meaning not established
  8       01 for observed audio; short stop packets use other values
  9..11   00 03 f0, consistent with 1008-byte format-plus-PCM length
 12..15   Big-endian seconds on the source's local clock
 16..19   Big-endian microseconds
 20..23   Big-endian PCM byte position, resets at restart
 24..27   02 10 ac44, consistent with 2 channels, 16 bits, 44100 Hz
 28..     1004 bytes of little-endian PCM, with trailing zeros omitted on wire
The meanings of flag bits and other packet types remain unresolved.

Clock
Observed 48-byte requests/replies on source UDP port 12300 have NTP-style
structure. Reply echoes the request transmit timestamp into origin field.
Seconds use the NTP epoch offset plus the same local seconds as audio packets.
Fraction fields use the standard NTP binary fraction: floor(microseconds *
2^32 / 1,000,000). The earlier shift-by-12 inference from one reply was wrong.
Re-analysis of 115 real-source replies found 0.16 ms offset standard deviation
with standard NTP decoding, versus 15.93 ms with the earlier interpretation.
That approximation creates up to 46.3 ms of error and a jump each second.
Tests now check known half/quarter-second values and continuity at rollover.
A complete clock servo, drift handling and playout policy remain absent.

Earlier live findings (superseded in part by the group-member success)
1. AudioIn/StartTransmissionToGroup on the real Connect succeeds over ordinary
   HTTP and returns multicast, source ports and source device ID. The observed
   native audio itself was unicast UDP to receiver port 7020.
2. AVTransport/ChangeTransportSettings to point the receiver at the Mac fails
   with UPnP 800. No experimental audio packets were sent in that test.
   Error 800 alone does not establish authentication as the cause.
3. TCP 1843 requests a TLS client certificate; a handshake without one is
   closed. This is concrete evidence that this secure endpoint has a client
   authentication requirement, not proof that every setup route needs it.
4. A synthetic source was advertised briefly and multiple speakers fetched its
   description, including the target receiver in the first trial. Selecting
   its line-in URI failed with UPnP 402 before StartTransmissionToGroup arrived.
   A second trial corrected embedded service IDs and supplied line-in metadata;
   selection still failed. Missing device behavior/registration may explain it.
5. Experimental advertisements were withdrawn. Final verification: original
   Airplay Connect URI, PAUSED_PLAYBACK, CurrentMute=0 on Server Room.
   Volume was not changed by the probes.

App HAR findings
The supplied HAR includes 67 decoded binary WebSocket JSON messages. The app
uses playback/loadLineIn with deviceId, instanceId and playOnCompletion, then
receives playback/metadata status. This selects an existing Sonos source; it
contains neither the audio stream nor a replacement transport endpoint.
The HAR also contains authentication material. It is not included in this lab,
not published and not needed to run the offline decoder. Controller access
must not be confused with speaker-to-speaker device authentication.

What remains before a real bridge
- Determine why the receiver rejects the synthetic source: validate discovery,
  eventing and household recognition rather than assuming TLS is the only cause.
- Establish a supported or reproducible way to negotiate native transport with
  the receiver. The current sender cannot establish its own playback session.
- Implement control/end packets, retransmission/feedback and clock drift handling.
- Confirm recovered PCM by listening and test silence and known tones.
- Only then connect the sender to AirConnect's decoded AirPlay PCM output and
  measure actual end-to-end latency. AirPlay buffering would still remain.

These results are a research prototype, not a deployable native Sonos bridge.
Run probe scripts as standalone commands, not as importable modules.
