#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/stat.h>
#include <jansson.h>
#include "sonos_api.h"

int main(int argc, char **argv) {
    char name[256];
    const char *valid = "[{\"coordinator\":{\"uuid\":\"RINCON_A\",\"roomName\":\"Kitchen & Dining\"},\"members\":[{\"uuid\":\"RINCON_B\",\"roomName\":\"Slave\"}]}]";
    assert(sonos_api_parse(valid, strlen(valid)));
    assert(sonos_api_name("uuid:RINCON_A", name, sizeof(name)));
    assert(!strcmp(name, "Kitchen & Dining (Sonos)"));
    assert(!sonos_api_name("uuid:RINCON_B", name, sizeof(name)));
    assert(!sonos_api_name("uuid:RINCON_A", name, 2));
    const char *bad[] = {"null", "[]", "{}", "garbage", "[{}]", "[{\"coordinator\":{\"uuid\":\"RINCON_A\"}}]", "[{\"coordinator\":{\"uuid\":\"RINCON_A\",\"roomName\":\"A\"}},{\"coordinator\":{\"uuid\":\"RINCON_A\",\"roomName\":\"B\"}}]"};
    for (size_t i = 0; i < sizeof(bad)/sizeof(*bad); i++) {
        assert(!sonos_api_parse(bad[i], strlen(bad[i])));
        assert(sonos_api_name("uuid:RINCON_A", name, sizeof(name)));
        assert(!strcmp(name, "Kitchen & Dining (Sonos)"));
    }
    strcpy(glSonosPrefix, "Home: ");
    assert(sonos_api_parse(valid, strlen(valid)));
    assert(sonos_api_name("uuid:RINCON_A", name, sizeof(name)));
    assert(!strcmp(name, "Home: Kitchen & Dining (Sonos)"));
    *glSonosPrefix = 0;
    char directory[] = "/tmp/airconnect-cache-XXXXXX";
    assert(mkdtemp(directory));
    snprintf(glSonosCache, sizeof(glSonosCache), "%s/rooms.json", directory);
    strcpy(glSonosAPI, "http://example.invalid:5005/zones");
    assert(!sonos_api_cache_load());
    assert(sonos_api_cache_save(valid, strlen(valid)));
    struct stat st;
    assert(!stat(glSonosCache, &st) && (st.st_mode & 0777) == 0600);
    json_error_t err;
    json_t *cache = json_load_file(glSonosCache, 0, &err);
    assert(cache && !json_object_get(json_array_get(json_object_get(cache, "zones"), 0), "members"));
    strcpy(glSonosPrefix, "Cached: ");
    assert(sonos_api_cache_load());
    assert(sonos_api_name("uuid:RINCON_A", name, sizeof(name)));
    assert(!strcmp(name, "Cached: Kitchen & Dining (Sonos)"));
    assert(!sonos_api_cache_save("[]", 2)); /* bad response cannot poison cache */
    assert(sonos_api_cache_load());
    strcat(glSonosAPI, "-different");
    assert(!sonos_api_cache_load());
    strcpy(glSonosAPI, "http://example.invalid:5005/zones");
    json_int_t stamp = json_integer_value(json_object_get(cache, "fetched_at"));
    json_object_set_new(cache, "fetched_at", json_integer(stamp - 86401));
    assert(!json_dump_file(cache, glSonosCache, 0));
    assert(!sonos_api_cache_load());
    json_object_set_new(cache, "fetched_at", json_integer(stamp + 86400));
    assert(!json_dump_file(cache, glSonosCache, 0));
    assert(!sonos_api_cache_load());
    json_decref(cache);
    FILE *broken = fopen(glSonosCache, "wb");
    assert(broken && fputs("{truncated", broken) >= 0 && !fclose(broken));
    assert(!sonos_api_cache_load());
    assert(sonos_api_name("uuid:RINCON_A", name, sizeof(name))); /* last valid memory snapshot retained */
    unlink(glSonosCache);
    rmdir(directory);
    *glSonosCache = *glSonosAPI = *glSonosPrefix = 0;
    puts("Room cache tests passed (private atomic file, minimal data, URL binding, expiry, corrupt data, naming changes)");
    puts("Sonos API tests passed (coordinators only, names, invalid/duplicate payloads, atomic snapshot)");
    if (argc > 1) {
        snprintf(glSonosAPI, sizeof(glSonosAPI), "%s", argv[1]);
        if (argc > 2) snprintf(glSonosCache, sizeof(glSonosCache), "%s", argv[2]);
        if (!sonos_api_fetch()) return 1;
        puts("HTTP /zones fetch and validation passed");
    }
}
