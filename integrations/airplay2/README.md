# Experimental AirPlay 2 frontend

This optional frontend combines pinned Shairport Sync/NQPTP with an AirConnect timed Sonos worker. It is under development and is **not included in the normal installer or released ARM binaries**. Keep the existing AirPlay frontend available for rollback. The real Sonos helper is still required.

The initial integration targets one separately named test destination. Independent rooms, synchronized acoustic output, long-duration playback and end-to-end iPhone behavior must be validated before a general rollout. This is not an AirPlay 1 service merely advertising AirPlay 2 capability bits.

## Components

- Shairport Sync handles AirPlay discovery, pairing, decoding and source timing. `audio_airconnect.c` implements an additional output backend.
- One NQPTP daemon supplies AirPlay 2 clock information on the frontend host. Use the matched revisions below.
- A child `airconnect-ap2-worker` runs the existing native Sonos setup/sender/restoration code. Audio/control use private anonymous pipes, with bounded timestamped PCM messages.
- The worker produces continuous native silence during setup/flush and places source samples on a continuous output timeline. It refuses queue overflow; it does not enable the intercom sender's time-rebasing recovery.

All source formats are converted to **stereo S16_LE at 44,100 Hz**. The iPhone's software volume is applied by the frontend; `speaker_volume` sets the separate speaker level/ceiling for the session. `muted = true` is the default in the example. Native title/artwork display is unchanged and remains unfinished.

The frontend converts its clock to the worker's same-host CLOCK_MONOTONIC domain. The queue is limited to two seconds, not a requirement to delay playback by two seconds. Requested frontend buffering is 200 ms; native packet lead is 75 ms. These are implementation parameters, not measured acoustic latency. No DAC-derived drift correction or accurate speaker-delay feedback is claimed.

## Build only

Use a dependency-complete macOS or Linux development host. Do not assume the legacy CloudKey has suitable libraries. Follow the pinned upstream build requirements, including FFmpeg, libconfig, popt, libplist, libsodium, libgcrypt, OpenSSL and the platform's discovery library.

```sh
git clone https://github.com/mikebrady/shairport-sync.git /absolute/path/shairport-sync
git -C /absolute/path/shairport-sync checkout cf6998daa1876c5a8f97128a960c8afc0e731841
git clone https://github.com/mikebrady/nqptp.git /absolute/path/nqptp
git -C /absolute/path/nqptp checkout ab8fb67483411640fd7f1e193889482f2421c37c

# From this AirConnect checkout, after prepare-source.sh:
sh integrations/airplay2/build-frontend.sh /absolute/path/shairport-sync
sh integrations/airplay2/build-worker.sh
sh integrations/airplay2/test.sh /absolute/path/shairport-sync
```

The worker script defaults to macOS ARM64. Set `HOST=linux PLATFORM=arm CC=gcc` for the existing ARMv7 dependency archives, or `HOST=macos PLATFORM=x86_64` for the Intel Mac archives. It builds its own cross-platform support objects and does not replace the installed AirPlay or intercom binaries. A suitable frontend/dependency build is a separate requirement.

The frontend script verifies the exact upstream revision and adds the backend to that checkout. It neither installs nor starts a service. Build NQPTP from its own source directory using `autoreconf -fi`, `./configure`, and `make`; its privileged ports and startup configuration are host-specific. Review [upstream documentation](https://github.com/mikebrady/nqptp) before running it.

## Test configuration

Copy [the example](airconnect.conf.example) to a private location and replace the paths, addresses and receiver UUID. It intentionally starts muted. Run the compiled frontend with `-c /absolute/path/config -v` only when the timing daemon and receiver are ready for testing. A renamed copy of this example is not proof that the AirPlay 2 audio path works.

The frontend and worker must run on the **same host**. Device ownership also needs coordination with every other native sender. Existing leases are per host/user/temp directory: running a second bridge on another machine does not automatically share ownership with the production bridge. Co-locate services for production, or supply a separately verified ownership guard. Do not expose this internal pipe protocol over the network as a raw timestamped stream.

Use one unique name, port, stable AirPlay identity and timing interface per room. Exclude the helper as a destination. The inspected NQPTP has a 16-client limit; review capacity before advertising more rooms. Do not claim synchronized multiroom playback until acoustic and drift tests pass.

## Tests and failure behavior

Offline tests cover deadline placement, continuous samples under small timing variations, flush, old/late input, bounded future input, ring wrap, format negotiation, clock-domain conversion and preparation failure. `tests/ap2_native_driver.py` can run the new worker through the existing simulated Sonos lifecycle suite:

```sh
NATIVE_TEST_DRIVER="$PWD/tests/ap2_native_driver.py" python3 tests/test_native_control.py
```

On macOS, also set `NATIVE_TEST_HELPER_IP` to a local interface address for the second simulated device. This is a simulator address on the test host, not a real helper address. The harness verifies normal restoration, delayed topology, bounded failed promotion/separation and refusal of a busy helper.

The upstream core does not reliably propagate backend prepare/play return values. The adapter therefore exits the experimental frontend on a failed preparation or worker loss; it does not claim successful silent playback. Graceful stop closes the pipe and waits for worker restoration. Forced termination is reported as unverified restoration and requires checking speaker state.

## Attribution

Shairport Sync remains a separate upstream checkout with its own [LICENSES](https://github.com/mikebrady/shairport-sync/blob/cf6998daa1876c5a8f97128a960c8afc0e731841/LICENSES); preserve its notices when redistributing a modified build. NQPTP is a separate GPLv2 component, with source/license obligations of its own. The original adapter/timeline/worker files here use this repository's license. Dependency licenses still apply; no bundled combined release is provided by these scripts.

See [the initial design assessment](../../research/airplay2/README.md) for background. Household configurations, pairing identities, credentials and private deployment wrappers are intentionally excluded.
