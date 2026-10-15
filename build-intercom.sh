#!/bin/sh
set -eu
cd "$(dirname "$0")"
: "${HOST:=linux}" "${PLATFORM:=arm}" "${CC:=gcc}"
out=build/intercom
mkdir -p "$out" bin
$CC -std=gnu99 -O2 -D_GNU_SOURCE -DUPNP_STATIC_LIB \
 -Iairupnp/src -Icommon/libraop/src -Icommon/crosstools/src \
 -Icommon/libmdns/targets/include/mdnssvc -Icommon/libmdns/targets/include/mdnssd \
 -Iresearch/sonos-native/native \
 -Icommon/libpupnp/targets/$HOST/$PLATFORM/include/upnp \
 -Icommon/libpupnp/targets/$HOST/$PLATFORM/include/ixml \
 -Icommon/libpupnp/targets/$HOST/$PLATFORM/include/addons \
 -Iaircast/libjansson/targets/$HOST/$PLATFORM/include \
 tools/intercom_worker.c airupnp/src/sonos_native.c \
 research/sonos-native/native/sonos_sender.c research/sonos-native/native/sonos_packet.c \
 bin/$HOST/$PLATFORM/cross_log.o bin/$HOST/$PLATFORM/cross_util.o bin/$HOST/$PLATFORM/platform.o \
 common/libpupnp/targets/$HOST/$PLATFORM/libpupnp.a \
 aircast/libjansson/targets/$HOST/$PLATFORM/libjansson.a \
 -lpthread -o bin/airconnect-intercom-worker
