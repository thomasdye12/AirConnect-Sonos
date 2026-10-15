#include "audio.h"
#include "common.h"
#include <assert.h>
#include <string.h>
#include <time.h>
struct test_config config;
extern audio_output audio_airconnect;
uint64_t get_absolute_time_in_ns(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000+t.tv_nsec+9000000000ULL;}
int main(int argc,char **argv) {
    assert(argc==2 || argc==3);config_t cfg;config_init(&cfg);assert(config_read_file(&cfg,argv[1]));config.cfg=&cfg;
    assert(!audio_airconnect.init(0,NULL));
    assert(!audio_airconnect.configure(audio_airconnect.get_configuration(8,48000,9),NULL));
    assert(audio_airconnect.configure(0,NULL)!=0);
    assert(!audio_airconnect.prepare());
    if(argc==3){struct timespec t={0,200000000};nanosleep(&t,NULL);audio_airconnect.is_running();return 20;}
    uint8_t pcm[4096*4];memset(pcm,0x23,sizeof(pcm));
    assert(!audio_airconnect.play(pcm,352,play_samples_are_untimed,0,0));
    assert(!audio_airconnect.play(pcm,4096,play_samples_are_timed,0,get_absolute_time_in_ns()+200000000));
    audio_airconnect.flush();
    assert(!audio_airconnect.play(pcm,352,play_samples_are_timed,0,get_absolute_time_in_ns()+200000000));
    assert(!audio_airconnect.is_running());
    audio_airconnect.stop();config_destroy(&cfg);return 0;
}
