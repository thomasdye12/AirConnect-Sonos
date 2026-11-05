#ifndef AP2_TEST_COMMON_H
#define AP2_TEST_COMMON_H
#include <stdint.h>
#include <libconfig.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
struct test_config {config_t *cfg;double audio_backend_buffer_desired_length,audio_backend_latency_offset;};
extern struct test_config config;
uint64_t get_absolute_time_in_ns(void);
#define CHANNELS_TO_ENCODED_FORMAT(v) ((v)<<25)
#define RATE_TO_ENCODED_FORMAT(v) (((v)/2)<<6)
#define FORMAT_TO_ENCODED_FORMAT(v) (v)
#define SPS_FORMAT_S16_LE 2
static inline void test_log(const char *format,...){va_list a;va_start(a,format);vfprintf(stderr,format,a);va_end(a);fputc('\n',stderr);}
#define debug(level,...) test_log(__VA_ARGS__)
#define warn(...) test_log(__VA_ARGS__)
#define die(...) do {test_log(__VA_ARGS__);exit(10);} while(0)
#endif
