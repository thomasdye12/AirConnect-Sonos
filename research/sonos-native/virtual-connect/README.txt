ARCHIVED EXPERIMENT: see ../README.md. The machine-specific launcher mentioned
below is not distributed. Default to local-only inspection; pairing is unresolved.
Do not follow historical Add Product steps as a verified installation procedure.

DIAGNOSTICS UPDATE: TLS logging now records handshake stages and alert codes,
without payloads. Experimental LAN mode also listens passively on UDP 6969,
identified in the older stock netstartd. It logs length and the first two header
bytes only; it neither saves configuration payloads nor replies to setup packets.
The observer is not an implementation of pairing. A successful local TLS smoke
test does not mean iOS accepts the experimental certificate.

CURRENT TEST: The user requested discovery be re-enabled using another speaker's
public description. The launcher now uses --advertise and the locally cached
Connect profile in work/virtual-connect/reference. All nested device structure,
service schemas and numeric capability fields are retained for compatibility;
these declarations do not mean the corresponding behaviours are implemented.
UUID, MAC and serial are replaced throughout with a separate virtual identity.
Unsupported actions still return errors. Certificate enrollment remains absent.
App stability is not yet confirmed. The experiment stops after 30 minutes.
Run without --advertise for localhost-only inspection. Do not run two copies.

The notes below describe earlier revisions and are historical:

CRASH REPORT UPDATE: The supplied iOS report shows an uncaught std::stoi
invalid_argument. Numeric descriptor omissions and the wrong zoneType have
been corrected as candidate causes. Exact offending field remains unknown;
this is not a verified crash fix. Discovery remains disabled by default.

UPDATE: iOS app crash reported during the first discovery experiment.
The cause is NOT established. The prototype has been stopped. The default
launcher now uses localhost only and does NOT advertise to Sonos. Do not repeat
the Add Product instructions below until controller compatibility is resolved.
CLI --advertise explicitly enables the experimental, unverified LAN mode.
A malformed SOAP fault namespace was corrected, but logs show no corresponding
request from the phone, so this is NOT a verified fix for the crash.

Historical first-test instructions (discovery currently disabled by default):

Virtual Connect Lab — experimental discovery/setup observer

Run on this Mac
Double-click Start Virtual Connect.command, or run virtual_connect.py with:
  --bind <Mac LAN IPv4> --observe <Sonos IPv4> --state <private state directory>
The launcher uses Server Room (192.0.2.70) to choose the Mac's network interface.
It stores identity, generated test certificate/private key and logs in
work/virtual-connect, outside this deliverable folder. Python 3 and openssl
are required. The process automatically stops after 30 minutes. Ctrl-C stops
it sooner. Do not start a second copy while one is running.

Try it
1. Open http://<Mac LAN IPv4>:1400 for live status.
2. Open the Sonos app on your home network and try Add Product.
3. Look for Virtual Connect Lab. Report whether it appears and the exact step
   or error shown. If it does not appear, the dashboard requests and topology
   observation help distinguish discovery failure from rejected trust.
4. Do not reset an existing speaker. This experiment advertises a new identity.

Implemented
Persistent locally generated identity; SSDP announcements and responses;
standalone device/service XML; limited read-only SOAP actions; HTTP and TLS
listeners; request-name/argument-name logging; optional read-only topology
checks; status page; clean signal shutdown and SSDP withdrawal.
The firmware/model version fields are compatibility advertisements, not claims
that this software contains Sonos firmware or is certified by Sonos.

Not implemented
Actual unpaired setup protocol, setup challenge/confirmation, certificate
issuance, household enrollment, event subscriptions, group coordination,
AudioIn start/stop, or audio playback. The unpaired mode omits the household
advertisement; this alone is NOT a verified implementation of Sonos setup mode.
Unsupported SOAP actions return a fault, never fake registration success.
The self-signed certificate is expected to be rejected by trusted Sonos peers.
The status page always reports enrolled=false and audio_available=false.
No real device certificate/private key is copied. No account credentials are
requested. Request bodies, HTTP header values and query values are not logged.
Private local logs still include LAN addresses and request/argument names.

Lifecycle
Requires free TCP ports 1400, 1443 and 1843, and UDP multicast port 1900.
Normal exit withdraws advertisements; forced termination can leave cached
entries until advertisement expiry. Existing speakers are not reconfigured.
To return to household discovery instead of the unpaired experiment, the CLI
accepts --household <ID>; it does not grant membership or certificate trust.

Validation
Unit checks cover persistent identity, unpaired advertisement, withdrawal,
XML escaping and fault encoding. Live smoke checks validate descriptor/SOAP
responses and that a dummy request-body secret is absent from the status log.
Enrollment and app visibility are unverified until you test the controller.
