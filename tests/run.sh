#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p tests/bin
: "${CC:=clang}" "${HOST:=macos}" "${PLATFORM:=arm64}"
FLAGS="-g -fsanitize=address,undefined -fno-omit-frame-pointer"
"$CC" $FLAGS -Icommon/libraop/src tests/test_metadata.c -o tests/bin/test_metadata
"$CC" $FLAGS -Iairupnp/src -I"aircast/libjansson/targets/$HOST/$PLATFORM/include" \
    -I"common/libpupnp/targets/$HOST/$PLATFORM/include/upnp" \
    -I"common/libpupnp/targets/$HOST/$PLATFORM/include/ixml" \
    tests/test_sonos_api.c airupnp/src/sonos_api.c \
    "aircast/libjansson/targets/$HOST/$PLATFORM/libjansson.a" \
    "common/libpupnp/targets/$HOST/$PLATFORM/libpupnp.a" -lpthread -o tests/bin/test_sonos_api
tests/bin/test_metadata
tests/bin/test_sonos_api "$@"
