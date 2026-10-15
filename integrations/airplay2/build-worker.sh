#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
: "${HOST:=macos}" "${PLATFORM:=arm64}" "${CC:=clang}"
mkdir -p bin
$CC -std=gnu99 -O2 -D_GNU_SOURCE -DUPNP_STATIC_LIB \
 -Iintegrations/airplay2 -Iairupnp/src -Icommon/libraop/src -Icommon/crosstools/src \
 -Icommon/libmdns/targets/include/mdnssvc -Icommon/libmdns/targets/include/mdnssd \
 -Iresearch/sonos-native/native \
 -Icommon/libpupnp/targets/$HOST/$PLATFORM/include/upnp \
 -Icommon/libpupnp/targets/$HOST/$PLATFORM/include/ixml \
 -Icommon/libpupnp/targets/$HOST/$PLATFORM/include/addons \
 -Iaircast/libjansson/targets/$HOST/$PLATFORM/include \
 integrations/airplay2/worker.c integrations/airplay2/timeline.c airupnp/src/sonos_native.c \
 research/sonos-native/native/sonos_sender.c research/sonos-native/native/sonos_packet.c \
 common/crosstools/src/cross_log.c common/crosstools/src/cross_util.c common/crosstools/src/platform.c \
 common/libpupnp/targets/$HOST/$PLATFORM/libpupnp.a \
 aircast/libjansson/targets/$HOST/$PLATFORM/libjansson.a -lpthread ${LDFLAGS:-} -o bin/airconnect-ap2-worker
