#include <assert.h>
#include <stdlib.h>
#include "raop_metadata_util.h"

int main(void) {
    uint8_t packet[RAOP_ICY_MAX];
    size_t size = raop_icy_packet(packet, NULL, "AirPlay from iPhone", NULL);
    assert(size == 1 + packet[0] * 16);
    assert(!strcmp((char*)packet + 1, "StreamTitle='AirPlay from iPhone';"));
    raop_icy_packet(packet, "Artist", "Track", "http://127.0.0.1/cover.png");
    assert(!strcmp((char*)packet + 1, "StreamTitle='Artist - Track';StreamURL='http://127.0.0.1/cover.png';"));
    raop_icy_packet(packet, NULL, "It's\nplaying", NULL);
    assert(!strcmp((char*)packet + 1, "StreamTitle='It`s playing';"));
    char *long_text = malloc(100000);
    memset(long_text, 'a', 99999); long_text[99999] = 0;
    size = raop_icy_packet(packet, long_text, long_text, long_text);
    assert(size <= sizeof(packet));
    size_t text_len = strlen((char*)packet + 1);
    for (size_t i = text_len + 1; i < size; i++) assert(packet[i] == 0);
    char unicode[5];
    raop_icy_text(unicode, sizeof(unicode), "abc\xc3\xa9");
    assert(!strcmp(unicode, "abc"));
    assert(raop_image_type("image/png", "\x89PNG\r\n\x1a\n", 8));
    assert(raop_image_type("image/jpeg", "\xff\xd8\xff", 3));
    assert(!raop_image_type("image/jpeg", "not an image", 12));
    assert(!raop_image_type("image/png", "\x89PNG\r\n\x1a\n", 4 * 1024 * 1024 + 1));
    free(long_text);
    puts("Metadata tests passed (null fields, artwork, quoting, long fields, UTF-8, image limits)");
}
