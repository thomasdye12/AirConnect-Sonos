/* AirConnect timed PCM queue. MIT; see repository LICENSE. */
#ifndef AC_AP2_TIMELINE_H
#define AC_AP2_TIMELINE_H
#include <stdint.h>
#include <stddef.h>
#define AP2_RATE 44100
#define AP2_CAPACITY (AP2_RATE * 2)
#define AP2_MAX_FRAMES 4096
struct ap2_timeline {
    uint8_t pcm[AP2_CAPACITY * 4];
    int64_t tags[AP2_CAPACITY];
    int64_t cursor, next_input;
    uint64_t epoch_ns, late_frames, silence_frames, realignments;
    int aligned;
};
void ap2_timeline_init(struct ap2_timeline *q, uint64_t epoch_ns);
void ap2_timeline_flush(struct ap2_timeline *q);
/* Reject over-capacity or absurd timestamps, rather than overwrite future audio. */
int ap2_timeline_push(struct ap2_timeline *q, const uint8_t *pcm, size_t frames, uint64_t when_ns);
void ap2_timeline_render(struct ap2_timeline *q, uint8_t *pcm, size_t frames);
#endif
