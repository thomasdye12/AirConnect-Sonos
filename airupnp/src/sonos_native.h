/* Native Sonos output for AirPlay PCM. Original AirConnect licensing applies. */
#pragma once
#include "raop_server.h"
struct sonos_native_device;
extern char glNativeHelperConfig[512];
int sonos_native_load_helper(void);
int sonos_native_is_helper(const char *udn);
struct sonos_native_device *sonos_native_device_new(const char *local, const char *location, const char *udn, int muted);
void sonos_native_device_free(struct sonos_native_device *d);
raop_pcm_output_t sonos_native_output(struct sonos_native_device *d);
void sonos_native_volume(struct sonos_native_device *d, int volume);
/* True after independent receiver promotion and helper restoration. */
int sonos_native_session_ready(void *session);
/* Last setup/control failure, copied under the device lock. */
void sonos_native_get_error(struct sonos_native_device *d, char *buffer, size_t size);
