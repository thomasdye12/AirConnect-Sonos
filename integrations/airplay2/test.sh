#!/bin/sh
# Offline checks; no speaker or LAN access. Requires prepared Shairport source.
set -eu
src=${1:?Usage: test.sh /absolute/shairport-checkout}
cd "$(dirname "$0")/../.."
: "${CC:=clang}"
mkdir -p tests/bin
$CC -std=c99 -g -fsanitize=address,undefined -Iintegrations/airplay2 \
 tests/test_ap2_timeline.c integrations/airplay2/timeline.c -o tests/bin/test_ap2_timeline
tests/bin/test_ap2_timeline
$CC -D_POSIX_C_SOURCE=200809L -std=c99 -Itests/ap2-stubs -I"$src" -Iintegrations/airplay2 \
 $(pkg-config --cflags libconfig) tests/test_ap2_backend.c integrations/airplay2/audio_airconnect.c \
 $(pkg-config --libs libconfig) -lpthread -o tests/bin/test_ap2_backend
python3 tests/test_ap2_backend.py
