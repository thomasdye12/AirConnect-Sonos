#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <jansson.h>
#include "upnp.h"
#include "sonos_api.h"

#define MAX_ZONES 128
#define MAX_RESPONSE (1024 * 1024)

char glSonosAPI[1024] = "";
char glSonosPrefix[128] = "";
char glSonosSuffix[128] = " (Sonos)";
struct zone { char udn[250]; char name[256]; };
static struct zone zones[MAX_ZONES];
static size_t zone_count;

/* Validate the entire response before replacing the previous snapshot. */
bool sonos_api_parse(const char *text, size_t length) {
    json_error_t error;
    json_t *root = json_loadb(text, length, JSON_REJECT_DUPLICATES, &error);
    struct zone *next = calloc(MAX_ZONES, sizeof(*next));
    bool ok = false;
    size_t count = json_array_size(root);
    if (!next || !json_is_array(root) || !count || count > MAX_ZONES) goto done;

    for (size_t i = 0; i < count; i++) {
        json_t *coordinator = json_object_get(json_array_get(root, i), "coordinator");
        const char *uuid = json_string_value(json_object_get(coordinator, "uuid"));
        const char *room = json_string_value(json_object_get(coordinator, "roomName"));
        if (!uuid || strncmp(uuid, "RINCON_", 7) || !room || !*room) goto done;
        int n = snprintf(next[i].udn, sizeof(next[i].udn), "uuid:%s", uuid);
        if (n < 0 || (size_t)n >= sizeof(next[i].udn)) goto done;
        n = snprintf(next[i].name, sizeof(next[i].name), "%s%s%s", glSonosPrefix, room, glSonosSuffix);
        if (n < 0 || (size_t)n >= sizeof(next[i].name)) goto done;
        for (size_t j = 0; j < i; j++) if (!strcmp(next[j].udn, next[i].udn)) goto done;
    }
    memcpy(zones, next, count * sizeof(*next));
    zone_count = count;
    ok = true;
done:
    free(next);
    json_decref(root);
    return ok;
}

bool sonos_api_name(const char *udn, char *name, size_t capacity) {
    for (size_t i = 0; i < zone_count; i++) {
        if (!strcmp(udn, zones[i].udn)) {
            if (strlen(zones[i].name) >= capacity) return false;
            strcpy(name, zones[i].name);
            return true;
        }
    }
    return false;
}

bool sonos_api_fetch(void) {
    void *handle = NULL;
    char *type = NULL, *body = NULL;
    int length = 0, status = 0;
    size_t used = 0;
    bool ok = false;
    /* The existing Sonos HTTP API is local HTTP. Do not silently accept HTTPS. */
    if (strncmp(glSonosAPI, "http://", 7)) return false;
    if (UpnpOpenHttpGet(glSonosAPI, &handle, &type, &length, &status, 5) != UPNP_E_SUCCESS) goto done;
    if (status != 200 || length > MAX_RESPONSE) goto done;
    body = malloc(MAX_RESPONSE + 1);
    if (!body) goto done;
    while (used < MAX_RESPONSE + 1) {
        size_t bytes = MAX_RESPONSE + 1 - used;
        if (UpnpReadHttpGet(handle, body + used, &bytes, 5) != UPNP_E_SUCCESS) goto done;
        if (!bytes) break;
        used += bytes;
    }
    if (used > MAX_RESPONSE) goto done;
    ok = sonos_api_parse(body, used);
done:
    if (handle) UpnpCloseHttpGet(handle);
    free(body);
    if (!ok) fprintf(stderr, "Sonos /zones API unavailable or invalid; refusing to publish an incorrect room list\n");
    return ok;
}
