#ifndef SONOS_SENDER_H
#define SONOS_SENDER_H
#include <stddef.h>
#include <stdint.h>
struct sonos_sender;
struct sonos_sender_stats { uint64_t packets, clock_requests, late_packets; };
/* Creates a single-target sender and timing service. Does not control speakers.
 * IPv4 addresses are numeric. clock_port=0 requests an ephemeral port for tests.
 * Audio must be canonical stereo signed 16-bit LE PCM at 44100 Hz. */
struct sonos_sender *sonos_sender_open(const char *local_ip,const char *peer_ip,
    uint16_t audio_port,uint16_t clock_port,uint32_t lead_us);
uint16_t sonos_sender_clock_port(struct sonos_sender *s);
/* Blocking, paced write. Single producer; buffers incomplete 251-frame packets.
 * Returns 0 on success, -1 on error; errno is set. */
int sonos_sender_write(struct sonos_sender *s,const uint8_t *pcm,size_t bytes);
void sonos_sender_get_stats(struct sonos_sender *s,struct sonos_sender_stats *stats);
/* Call after the producer has stopped. Partial packet is discarded. */
void sonos_sender_close(struct sonos_sender *s);
#endif
