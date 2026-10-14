#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
: "${CC:=clang}" "${HOST:=macos}" "${PLATFORM:=arm64}"
o="bin/$HOST/$PLATFORM"
$CC -std=gnu99 -g -D_GNU_SOURCE -DSSL_STATIC_LIB -Wno-deprecated-declarations \
 -Icommon/libraop/src -Icommon/crosstools/src -Icommon/dmap-parser \
 -Icommon/libmdns/targets/include/mdnssvc -Icommon/libmdns/targets/include/mdnssd \
 -I"common/libopenssl/targets/$HOST/$PLATFORM/include" -Icommon/libcodecs/targets/include/addons \
 tests/test_pcm_output.c "$o/cross_log.o" "$o/cross_util.o" "$o/cross_net.o" "$o/cross_thread.o" "$o/platform.o" "$o/cross_ssl-static.o" \
 "common/libraop/lib/$HOST/$PLATFORM/libraop.a" \
 "common/libcodecs/targets/$HOST/$PLATFORM/libcodecs.a" \
 "common/libmdns/targets/$HOST/$PLATFORM/libmdns.a" \
 "common/libopenssl/targets/$HOST/$PLATFORM/libopenssl.a" -lpthread -ldl -lm -o tests/bin/test_pcm_output
./tests/bin/test_pcm_output
