#include <assert.h>
#include <stdio.h>
#include <string.h>
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
    puts("Sonos API tests passed (coordinators only, names, invalid/duplicate payloads, atomic snapshot)");
    if (argc > 1) {
        snprintf(glSonosAPI, sizeof(glSonosAPI), "%s", argv[1]);
        if (!sonos_api_fetch()) return 1;
        puts("HTTP /zones fetch and validation passed");
    }
}
