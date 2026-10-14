#!/bin/sh
# Build changed C server code against the pinned upstream ARM archives.
# The old CloudKey compiler cannot compile upstream's unrelated C++17 client.
set -eu
cd "$(dirname "$0")"
mkdir -p build/cloudkey common/libraop/lib/linux/arm
for source in raop_server raop_streamer; do
    gcc -std=gnu99 -O2 -fPIC -D_GNU_SOURCE -DNDEBUG -DOPENSSL_SUPPRESS_DEPRECATED \
        -Icommon/libraop/src -Icommon/crosstools/src -Icommon/dmap-parser \
        -Icommon/libmdns/targets/include/mdnssvc -Icommon/libmdns/targets/include/mdnssd \
        -Icommon/libopenssl/targets/linux/arm/include \
        -Icommon/libcodecs/targets/include/addons -Icommon/libcodecs/targets/include/flac \
        -Icommon/libcodecs/targets/include/shine -Icommon/libcodecs/targets/include/faac \
        -c "common/libraop/src/$source.c" -o "build/cloudkey/$source.o"
done
cp common/libraop/targets/linux/arm/libraop.a common/libraop/lib/linux/arm/libraop.a
ar rcs common/libraop/lib/linux/arm/libraop.a build/cloudkey/raop_server.o build/cloudkey/raop_streamer.o
make -C airupnp CC=gcc HOST=linux PLATFORM=arm CPPFLAGS=-std=gnu99 \
    RAOP_LIBRARY=../common/libraop/lib/linux/arm/libraop.a -j2
