#!/bin/sh
set -eu
cd "$(dirname "$0")"
# Only top-level dependencies are needed; recursive checkout downloads many
# unrelated codec/crypto development repositories.
git submodule update --init --depth 1 common/crosstools common/dmap-parser \
    common/libcodecs common/libmdns common/libopenssl common/libpupnp \
    common/libraop aircast/libjansson
patch_file="$(pwd)/patches/libraop-tds.patch"
if git -C common/libraop apply --reverse --check "$patch_file" 2>/dev/null; then
    echo "Custom RAOP patch already applied"
elif git -C common/libraop apply --check "$patch_file"; then
    git -C common/libraop apply "$patch_file"
else
    # Upgrade published fork patches without discarding unrelated local edits.
    for version in tds3 tds2; do
        previous="$(pwd)/patches/libraop-$version.patch"
        if git -C common/libraop apply --reverse --check "$previous" 2>/dev/null; then
            git -C common/libraop apply --reverse "$previous"
            if git -C common/libraop apply --check "$patch_file"; then
                git -C common/libraop apply "$patch_file"
                exit 0
            else
                git -C common/libraop apply "$previous"
                echo "Native patch conflicts with local changes; restored the previous patch" >&2
                exit 1
            fi
        fi
    done
    echo "RAOP source differs from the expected base; refusing to overwrite changes" >&2
    exit 1
fi
