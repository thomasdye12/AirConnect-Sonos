/* Live PCM ingress for the existing native Sonos session implementation. */
#include "sonos_native.h"
#include "cross_log.h"
#include "jansson.h"
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
log_level main_loglevel=lINFO;
static volatile bool running=true;
static void stop(int sig) {(void)sig;running=false;}
static uint64_t millis(void) {
    struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);
    return (uint64_t)t.tv_sec*1000+t.tv_nsec/1000000;
}
#define CAPACITY 35280 /* 200 ms, stereo s16le / 44100 Hz */
#define PRIME 10584    /* 60 ms before starting or recovering an underrun */
static void report_error(struct sonos_native_device *d,const char *fallback) {
    char error[192];sonos_native_get_error(d,error,sizeof(error));
    json_t *message=json_pack("{s:s,s:s}","type","error","message",*error?error:fallback);
    char *text=json_dumps(message,JSON_COMPACT);
    if(text){puts(text);free(text);}json_decref(message);
}
int main(int argc,char **argv) {
    if(argc!=7)return 2;
    int volume=atoi(argv[5]),muted=atoi(argv[6]);
    if(volume<0||volume>100||(muted!=0&&muted!=1))return 2;
    signal(SIGTERM,stop);signal(SIGINT,stop);signal(SIGPIPE,SIG_IGN);
    setvbuf(stdout,NULL,_IOLBF,0);
    snprintf(glNativeHelperConfig,sizeof(glNativeHelperConfig),"%s",argv[1]);
    if(sonos_native_load_helper())return 3;
    struct sonos_native_device *d=sonos_native_device_new(argv[2],argv[3],argv[4],muted);
    if(!d)return 4;
    sonos_native_live_recovery(d);
    sonos_native_volume(d,volume);
    raop_pcm_output_t out=sonos_native_output(d);
    void *s=out.open(out.owner,&running);
    if(!s){report_error(d,"Speaker setup failed before UDP start");sonos_native_device_free(d);return 5;}
    fcntl(STDIN_FILENO,F_SETFL,fcntl(STDIN_FILENO,F_GETFL)|O_NONBLOCK);
    uint8_t queue[CAPACITY],input[16384],pcm[1004];size_t used=0;
    uint64_t started=millis(),report=started,received=0,dropped=0,silence=0,frames=0;
    int ready=0,primed=0,rc=0;uint64_t recoveries=0;
    while(running && millis()-started<600000) {
        if(!ready && sonos_native_session_ready(s)) {
            ready=1;puts("{\"type\":\"ready\",\"format\":\"s16le\",\"rate\":44100,\"channels\":2}");
        }
        ssize_t n=read(STDIN_FILENO,input,sizeof(input));
        if(n==0)break;
        if(n<0 && errno!=EAGAIN && errno!=EINTR){rc=6;break;}
        if(n>0) {
            received+=(size_t)n;
            if(used+(size_t)n>CAPACITY) {
                size_t discard=(used+(size_t)n-CAPACITY+3)&~(size_t)3;
                memmove(queue,queue+discard,used-discard);used-=discard;dropped+=discard/4;
            }
            memcpy(queue+used,input,(size_t)n);used+=(size_t)n;
        }
        memset(pcm,0,sizeof(pcm));
        if(!primed && used>=PRIME)primed=1;
        size_t take=primed ? (used<sizeof(pcm)?used:sizeof(pcm))&~(size_t)3 : 0;
        if(take){memcpy(pcm,queue,take);memmove(queue,queue+take,used-take);used-=take;}
        if(take<sizeof(pcm)){silence+=(sizeof(pcm)-take)/4;primed=0;}
        if(out.write(s,pcm,sizeof(pcm))){rc=7;break;}
        uint64_t recovered=sonos_native_session_recoveries(s);
        if(recovered!=recoveries){dropped+=used/4;used=0;primed=0;recoveries=recovered;}
        frames+=251;
        if(millis()-report>=1000) {
            printf("{\"type\":\"stats\",\"received_bytes\":%llu,\"output_frames\":%llu,\"dropped_frames\":%llu,\"silence_frames\":%llu,\"queued_frames\":%zu,\"recoveries\":%llu}\n",
                (unsigned long long)received,(unsigned long long)frames,(unsigned long long)dropped,(unsigned long long)silence,used/4,(unsigned long long)recoveries);
            report=millis();
        }
        if(!ready && millis()-started>15000){rc=8;break;}
    }
    if(rc)report_error(d,rc==8?"Speaker preparation timed out":"Native PCM sender stopped");
    out.close(s);sonos_native_device_free(d);
    printf("{\"type\":\"closed\",\"code\":%d,\"received_bytes\":%llu,\"dropped_frames\":%llu,\"recoveries\":%llu}\n",rc,(unsigned long long)received,(unsigned long long)dropped,(unsigned long long)recoveries);
    return rc;
}
