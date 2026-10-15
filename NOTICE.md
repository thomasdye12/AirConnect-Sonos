# Attribution and provenance

AirConnect-Sonos is a modified fork of [AirConnect](https://github.com/philippe44/AirConnect), by Philippe (`philippe_44@outlook.com`). It retains the original source notices, license file, repository history, and pinned dependency references.

- AirConnect base: `5fdb61e20de59bac5dbda9f6e2ed56ce549ccabd` (v1.12.4).
- Patched [libraop](https://github.com/philippe44/libraop) base: `f426d0f4896a48e12662abe46fa2c9ed4c190afb`.
- Fork modifications: native `/zones` naming and cache, metadata robustness, experimental artwork reception/lifetime handling, RAOP PCM/timing integration, helper-assisted Sonos UDP lifecycle and sender, controller, read-only dashboard, authenticated PCM intercom input, bounded recovery, tests and build/deployment documentation, prepared for Thomas Dye in October 2026. These additions build on the upstream bridge and retain its attribution.

The upstream AirConnect and libraop license notices identify the MIT license. Their third-party dependencies retain their own license terms; this notice does not relicense those dependencies or claim ownership of upstream work. Consult the license notices in each dependency before redistribution, particularly for bundled/static binaries.

The RAOP changes are supplied as `patches/libraop-tds.patch` against the exact upstream revision above. `prepare-source.sh` applies them locally. The corresponding upstream license remains in `common/libraop/LICENSE.txt` after dependency initialization.

AirConnect, Sonos, and Apple are referenced to identify interoperability and origin. This fork is not endorsed by those projects or companies.

The `research/sonos-native` tools were developed for this fork from observations and independently written protocol code. Reference projects: [sonos-fenway](https://github.com/trulyspinach/sonos-fenway) (static firmware analysis), [sonos-websocket](https://github.com/jjlawren/sonos-websocket) (local API wire format), and [aiosonos](https://github.com/music-assistant/aiosonos) (API behavior references). Research source and original prose are provided under the repository MIT license; this does not license Sonos firmware or third-party implementations. Firmware binaries, disassembly dumps, private captures, recorded music, credentials and generated keys are not distributed here.

The experimental `integrations/airplay2` frontend uses a separately obtained, pinned [Shairport Sync](https://github.com/mikebrady/shairport-sync) checkout and [NQPTP](https://github.com/mikebrady/nqptp). Shairport Sync retains its MIT-style and component-specific notices; NQPTP is a separate GPLv2 component. Their implementations and licenses are not replaced by this fork's license. The original adapter and timed worker in this repository do not constitute a bundled binary distribution. See [experimental build notes](integrations/airplay2/README.md).
