#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <jansson.h>
#include "upnp.h"
#include "sonos_api.h"

#define MAX_ZONES 128
#define MAX_RESPONSE (1024 * 1024)

char glSonosAPI[1024] = "";
char glSonosCache[1024] = "";
char glSonosPrefix[128] = "";
char glSonosSuffix[128] = " (Sonos)";
struct zone { char udn[250]; char name[256]; };
static struct zone zones[MAX_ZONES];
static size_t zone_count;

/* Validate the entire response before replacing the previous snapshot. */
bool sonos_api_parse(const char *text, size_t length) {
    if (!text || length > MAX_RESPONSE) return false;
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

/* Cache only coordinator identifiers and raw room names, never the full /zones
 * response (which may contain current media and other household information).
 * Names are decorated again on load so changed prefix/suffix settings apply. */
bool sonos_api_cache_save(const char *text, size_t length) {
    if (!*glSonosCache || !sonos_api_parse(text, length)) return false;
    json_error_t error;
    json_t *input = json_loadb(text, length, JSON_REJECT_DUPLICATES, &error);
    json_t *list = json_array(), *root = NULL;
    char *body = NULL, temporary[1100];
    FILE *file = NULL;
    bool ok = false;
    if (!input || !list) goto done;
    for (size_t i = 0; i < json_array_size(input); i++) {
        json_t *coordinator = json_object_get(json_array_get(input, i), "coordinator");
        json_t *entry = json_pack("{s:{s:s,s:s}}", "coordinator", "uuid",
            json_string_value(json_object_get(coordinator, "uuid")), "roomName",
            json_string_value(json_object_get(coordinator, "roomName")));
        if (!entry || json_array_append_new(list, entry)) goto done;
    }
    root = json_pack("{s:i,s:s,s:I,s:O}", "version", 1, "api", glSonosAPI,
                     "fetched_at", (json_int_t)time(NULL), "zones", list);
    if (!root || !(body = json_dumps(root, JSON_COMPACT))) goto done;
    snprintf(temporary, sizeof(temporary), "%s.XXXXXX", glSonosCache);
    int fd = mkstemp(temporary); /* same directory, private mode, atomic rename */
    if (fd < 0) goto done;
    file = fdopen(fd, "wb");
    if (!file) { close(fd); unlink(temporary); goto done; }
    size_t bytes = strlen(body);
    ok = fwrite(body, 1, bytes, file) == bytes && !fflush(file) && !fsync(fd);
    if (fclose(file)) ok = false;
    file = NULL;
    if (ok) ok = !rename(temporary, glSonosCache);
    if (!ok) unlink(temporary);
done:
    free(body);
    json_decref(input);
    json_decref(list);
    json_decref(root);
    return ok;
}

bool sonos_api_cache_load(void) {
    if (!*glSonosCache) return false;
    FILE *file = fopen(glSonosCache, "rb");
    if (!file) return false;
    char *text = malloc(MAX_RESPONSE + 1), *zones_text = NULL;
    json_t *root = NULL;
    json_error_t error;
    bool ok = false;
    if (!text) goto done;
    size_t bytes = fread(text, 1, MAX_RESPONSE + 1, file);
    if (ferror(file) || bytes > MAX_RESPONSE) goto done;
    root = json_loadb(text, bytes, JSON_REJECT_DUPLICATES, &error);
    const char *api = json_string_value(json_object_get(root, "api"));
    json_t *stamp = json_object_get(root, "fetched_at");
    json_int_t then = json_integer_value(stamp), now = (json_int_t)time(NULL);
    if (json_integer_value(json_object_get(root, "version")) != 1 ||
        !api || strcmp(api, glSonosAPI) || !json_is_integer(stamp) ||
        then <= 0 || then > now || now - then > 86400) goto done;
    zones_text = json_dumps(json_object_get(root, "zones"), JSON_COMPACT);
    if (zones_text) ok = sonos_api_parse(zones_text, strlen(zones_text));
done:
    fclose(file);
    free(text);
    free(zones_text);
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
    if (ok && *glSonosCache && !sonos_api_cache_save(body, used))
        fprintf(stderr, "Sonos room cache could not be saved; using validated live API response\n");
done:
    if (handle) UpnpCloseHttpGet(handle);
    free(body);
    if (!ok && sonos_api_cache_load()) {
        fprintf(stderr, "Sonos /zones API unavailable or invalid; using cached coordinators (less than 24 hours old). Group changes require a live API restart.\n");
        ok = true;
    }
    if (!ok) fprintf(stderr, "Sonos /zones API unavailable or invalid, no usable cache; refusing to publish an incorrect room list\n");
    return ok;
}
