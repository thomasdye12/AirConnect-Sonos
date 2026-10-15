#!/bin/sh
# Build inside a caller-supplied pinned Shairport checkout; never install/start it.
set -eu
src=${1:?Usage: build-frontend.sh /absolute/shairport-checkout}
root=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
expected=cf6998daa1876c5a8f97128a960c8afc0e731841
test "$(git -C "$src" rev-parse HEAD)" = "$expected" || { echo 'Unexpected upstream revision' >&2; exit 1; }
python3 - "$src" "$root" <<'PY'
from pathlib import Path
import sys
src,root=map(Path,sys.argv[1:])
for name in ('audio_airconnect.c','protocol.h','timeline.h'):
    (src/name).write_bytes((root/'integrations/airplay2'/name).read_bytes())
p=src/'audio.c';s=p.read_text()
if 'extern audio_output audio_airconnect;' not in s:
    needle='static audio_output *outputs[] = {'
    if s.count(needle)!=1:raise SystemExit('Unexpected audio registry')
    s=s.replace(needle,'extern audio_output audio_airconnect;\n\n'+needle+'\n    &audio_airconnect,')
    p.write_text(s)
p=src/'Makefile.am';s=p.read_text()
if 'audio_airconnect.c' not in s:
    needle='player.c audio.c loudness.c'
    if s.count(needle)!=1:raise SystemExit('Unexpected upstream Makefile')
    p.write_text(s.replace(needle,'player.c audio.c audio_airconnect.c loudness.c'))
PY
cd "$src"
case $(uname -s) in
 Darwin) os=darwin; mdns=--with-dns_sd ;;
 Linux) os=linux; mdns=--with-avahi ;;
 *) echo 'Build currently supports macOS/Linux only' >&2; exit 1 ;;
esac
autoreconf -fi
./configure --with-os="$os" --with-airplay-2 "$mdns" --with-ssl=openssl --with-metadata --with-metadata-pipe
make -j4
