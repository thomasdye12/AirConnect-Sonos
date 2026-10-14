#pragma once

#include <stdbool.h>
#include <stddef.h>

/* A startup snapshot, matching the original /zones PHP generator. */
extern char glSonosAPI[1024], glSonosPrefix[128], glSonosSuffix[128];
bool sonos_api_parse(const char *json, size_t length);
bool sonos_api_fetch(void);
bool sonos_api_name(const char *udn, char *name, size_t capacity);
