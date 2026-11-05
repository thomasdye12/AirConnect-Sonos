/* Private same-host child protocol; PCM is always stereo S16_LE at 44100 Hz.
 * 24-byte big-endian header: magic, type, frame count, reserved=0, time_ns.
 * Time is CLOCK_MONOTONIC, not Shairport's potentially raw monotonic clock. */
#ifndef AC_AP2_PROTOCOL_H
#define AC_AP2_PROTOCOL_H
#include <stdint.h>
#define AP2_MAGIC 0x41503253u
#define AP2_AUDIO 1u
#define AP2_FLUSH 2u
static inline void ap2_put32(uint8_t *p,uint32_t v){p[0]=v>>24;p[1]=v>>16;p[2]=v>>8;p[3]=v;}
static inline uint32_t ap2_get32(const uint8_t *p){return (uint32_t)p[0]<<24|(uint32_t)p[1]<<16|(uint32_t)p[2]<<8|p[3];}
static inline void ap2_put64(uint8_t *p,uint64_t v){ap2_put32(p,v>>32);ap2_put32(p+4,v);}
static inline uint64_t ap2_get64(const uint8_t *p){return (uint64_t)ap2_get32(p)<<32|ap2_get32(p+4);}
#endif
