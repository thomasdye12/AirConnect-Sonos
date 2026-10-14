# Attribution and provenance

AirConnect-Sonos is a modified fork of [AirConnect](https://github.com/philippe44/AirConnect), by Philippe (`philippe_44@outlook.com`). It retains the original source notices, license file, repository history, and pinned dependency references.

- AirConnect base: `5fdb61e20de59bac5dbda9f6e2ed56ce549ccabd` (v1.12.4).
- Patched [libraop](https://github.com/philippe44/libraop) base: `f426d0f4896a48e12662abe46fa2c9ed4c190afb`.
- Fork modifications: native `/zones` integration, metadata robustness, experimental artwork reception/lifetime handling, tests, and build/deployment documentation, prepared for Thomas Dye in October 2026.

The upstream AirConnect and libraop license notices identify the MIT license. Their third-party dependencies retain their own license terms; this notice does not relicense those dependencies or claim ownership of upstream work. Consult the license notices in each dependency before redistribution, particularly for bundled/static binaries.

The RAOP changes are supplied as `patches/libraop-tds.patch` against the exact upstream revision above. `prepare-source.sh` applies them locally. The corresponding upstream license remains in `common/libraop/LICENSE.txt` after dependency initialization.

AirConnect, Sonos, and Apple are referenced to identify interoperability and origin. This fork is not endorsed by those projects or companies.
