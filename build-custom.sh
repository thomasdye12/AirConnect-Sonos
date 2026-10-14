#!/bin/sh
set -eu
cd "$(dirname "$0")"
: "${CC:=clang}" "${CXX:=clang++}" "${HOST:=macos}" "${PLATFORM:=arm64}"
make -C common/libraop CC="$CC" CXX="$CXX" HOST="$HOST" PLATFORM="$PLATFORM" \
    TOOLS=../crosstools/src DMAP_PARSER=../dmap-parser MDNS=../libmdns/targets \
    CODECS=../libcodecs/targets OPENSSL="../libopenssl/targets/$HOST/$PLATFORM" lib -j4
make -C airupnp CC="$CC" HOST="$HOST" PLATFORM="$PLATFORM" \
    RAOP_LIBRARY="../common/libraop/lib/$HOST/$PLATFORM/libraop.a" -j4
