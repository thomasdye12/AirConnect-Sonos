#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
: "${HOST:=macos}" "${PLATFORM:=arm64}" "${CC:=clang}"
o="bin/$HOST/$PLATFORM"
mkdir -p tests/bin
$CC -g -D_GNU_SOURCE -DSSL_STATIC_LIB -Wno-deprecated-declarations \
 -Iairupnp/src -Icommon/libraop/src -Icommon/crosstools/src -Icommon/dmap-parser \
 -Icommon/libmdns/targets/include/mdnssvc -Icommon/libmdns/targets/include/mdnssd \
 -I"common/libopenssl/targets/$HOST/$PLATFORM/include" -Icommon/libcodecs/targets/include/addons \
 tests/raop_native_host.c "$o/sonos_native.o" "$o/sonos_sender.o" "$o/sonos_packet.o" \
 "$o/cross_log.o" "$o/cross_util.o" "$o/cross_net.o" "$o/cross_thread.o" "$o/platform.o" "$o/cross_ssl-static.o" \
 "common/libraop/lib/$HOST/$PLATFORM/libraop.a" \
 "common/libpupnp/targets/$HOST/$PLATFORM/libpupnp.a" \
 "aircast/libjansson/targets/$HOST/$PLATFORM/libjansson.a" \
 "common/libcodecs/targets/$HOST/$PLATFORM/libcodecs.a" \
 "common/libmdns/targets/$HOST/$PLATFORM/libmdns.a" \
 "common/libopenssl/targets/$HOST/$PLATFORM/libopenssl.a" -lpthread -ldl -lm -o tests/bin/raop_native_host
