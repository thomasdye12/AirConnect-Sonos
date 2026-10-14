#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
clang -g -fsanitize=address,undefined -D_GNU_SOURCE -DSSL_STATIC_LIB -Wno-deprecated-declarations \
-Icommon/libraop/src -Icommon/crosstools/src -Icommon/dmap-parser \
-Icommon/libmdns/targets/include/mdnssvc -Icommon/libmdns/targets/include/mdnssd \
-Icommon/libopenssl/targets/macos/arm64/include -Icommon/libcodecs/targets/include/addons \
tests/test_rtsp_metadata.c bin/macos/arm64/cross_util.o bin/macos/arm64/cross_net.o \
bin/macos/arm64/cross_log.o bin/macos/arm64/cross_thread.o bin/macos/arm64/platform.o \
bin/macos/arm64/cross_ssl-static.o common/libraop/lib/macos/arm64/libraop.a \
common/libcodecs/targets/macos/arm64/libcodecs.a common/libmdns/targets/macos/arm64/libmdns.a \
common/libopenssl/targets/macos/arm64/libopenssl.a -lpthread -ldl -lm -o tests/bin/test_rtsp_metadata
tests/bin/test_rtsp_metadata
