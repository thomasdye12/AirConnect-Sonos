#ifndef SONOS_PACKET_H
#define SONOS_PACKET_H
#include <stddef.h>
#include <stdint.h>
#define SONOS_PCM_BYTES 1004
#define SONOS_PACKET_BYTES 1032
/* Observed format: 251 frames, stereo signed 16-bit little-endian, 44100 Hz.
 * All sizes are in bytes. Returns encoded size, or zero on invalid input. */
size_t sonos_packet_encode(uint8_t *out, size_t capacity, uint16_t sequence,
                          uint64_t timestamp_us, uint32_t byte_position,
                          const uint8_t *pcm, size_t pcm_size);
/* Decodes only the observed audio format; returns 1 on success, 0 otherwise. */
int sonos_packet_decode(const uint8_t *packet, size_t size, uint16_t *sequence,
                        uint64_t *timestamp_us, uint32_t *byte_position,
                        uint8_t *pcm, size_t capacity);
/* Observed Sonos NTP-like reply; timestamps are local monotonic microseconds.
 * Does not discipline clocks or infer a playback delay. */
int sonos_clock_reply(uint8_t *out, size_t capacity, const uint8_t *request,
                      size_t request_size, uint64_t received_us, uint64_t sent_us);
#endif
