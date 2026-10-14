#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
: "${HOST:=macos}" "${PLATFORM:=arm64}" "${CC:=clang}"
o="bin/$HOST/$PLATFORM"
mkdir -p tests/bin
$CC -g -Iairupnp/src -Icommon/libraop/src -Icommon/crosstools/src \
 -Icommon/libmdns/targets/include/mdnssvc -Icommon/libmdns/targets/include/mdnssd \
 tests/native_output_driver.c "$o/sonos_native.o" "$o/sonos_sender.o" "$o/sonos_packet.o" \
 "$o/cross_log.o" "$o/cross_util.o" "$o/platform.o" \
 "common/libpupnp/targets/$HOST/$PLATFORM/libpupnp.a" \
 "aircast/libjansson/targets/$HOST/$PLATFORM/libjansson.a" -lpthread -o tests/bin/native_output_driver
