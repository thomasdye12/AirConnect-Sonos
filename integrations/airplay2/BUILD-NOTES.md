# Development build notes

The experimental frontend and worker compiled on Apple Silicon macOS and on an Intel macOS 10.13 host with a newer compiler. These are build observations, not a general support promise or completed AirPlay 2 playback certification.

For the Intel compatibility build, dependencies were installed in an isolated prefix, with no system library or existing application replacement:

| Component | Version/revision |
| --- | --- |
| Shairport Sync | `cf6998daa1876c5a8f97128a960c8afc0e731841` (5.6) |
| NQPTP | `ab8fb67483411640fd7f1e193889482f2421c37c` (1.2.9) |
| Compiler | MacPorts Clang 16; deployment target 10.13 |
| libconfig | 1.8.2, upstream commit `a42cb47c1526a4f2ed025fcbb2289863375bc898` |
| libplist | 2.2.0, upstream commit `c5a30e9267068436a75b5d00fcbf95cb9c1f4dcd` |
| FFmpeg | 7.1.1, audio-only static libraries, AAC/ALAC decoders and resampling |
| Existing libraries | libsodium 1.0.20, libgcrypt 1.10.3, popt 1.18, OpenSSL 3.1.5 |

Use a private `--prefix` and set `PKG_CONFIG_PATH` to its library metadata before system package locations. NQPTP and Shairport require a matched shared-memory interface (`smi11` in these builds). The macOS frontend configuration must explicitly include `--with-os=darwin`; upstream defaults to Linux otherwise.

The shipped x86_64 UPnP dependency archive references a newer macOS FD-set helper from unused networking routines. Linking this worker with `LDFLAGS=-Wl,-dead_strip` removed unused routines and allowed the build to link on 10.13. No replacement implementation of that bounds-checking function was supplied. Rebuild the dependency for the target OS if the required code still depends on unavailable symbols. Do not treat dead-stripping as a general compatibility fix.

A compiler link result does not establish runtime/network compatibility. The next checks are the standalone muted native worker, actual AirPlay 2 discovery and input, pause/seek/volume, restoration, and acoustic playback. Keep generated host configurations, keys and pairing state private.

## ARMv7 legacy Linux experiment

The frontend, NQPTP and worker also built and ran on ARMv7 hard-float Linux with glibc 2.19 and GCC 4.9.2. Dependencies were installed under a private prefix; system libraries and the existing bridge were not replaced. This is an experimental deployment, not an installer or a supported appliance upgrade.

The build used libconfig 1.8.2, libplist 2.2.0, popt 1.19, libsodium 1.0.22, libgpg-error 1.59, libgcrypt 1.11.3, FFmpeg 7.1.1, OpenSSL 3.5.9 and libuuid from util-linux 2.41.6. OpenSSL was linked statically; FFmpeg used shared libraries with AAC/ALAC decoding and resampling. Avahi headers matched the installed 0.6.31 runtime. Set `PKG_CONFIG_PATH`, include/library paths and the runtime library path to the private prefix. Shairport needs `--with-os=linux --with-airplay-2 --with-avahi --with-ssl=openssl --with-metadata --with-metadata-pipe`.

The system libuuid lacked `uuid_generate_sha1`. Build a private libuuid with `--disable-all-programs --enable-libuuid --disable-nls --disable-asciidoc --disable-static`; this old 32-bit libc additionally required `--disable-year2038`. That preserves its existing time ABI and does not solve the platform's year-2038 limitation. NQPTP and Shairport must use matching shared-memory names and interface versions.

Native ARM offline tests passed. A 20-second muted timed-PCM test delivered 882,000 frames with zero late input frames, including a flush; both speaker states were restored. Bonjour discovery and RTSP OPTIONS passed from another LAN host. After fixing backend initialization with forwarded CLI arguments, a local AirPlay 2 SETUP/TEARDOWN test returned success, started the native worker and verified restoration. These checks do not establish successful iPhone audio or acoustic quality; consult `validation.json` for the latest result.
