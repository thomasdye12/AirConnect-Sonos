/* Experimental AirPlay 2 timed PCM worker. MIT; repository LICENSE. */
#include "sonos_native.h"
#include "cross_log.h"
#include "timeline.h"
#include "protocol.h"
#include <errno.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
log_level main_loglevel=lINFO;
static volatile bool running=true;
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static struct ap2_timeline queue;
static int input_error;
static uint64_t received;
static void stop(int sig){(void)sig;running=false;}
static uint64_t now_ns(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000+t.tv_nsec;}
static int read_all(void *data,size_t size) {
    uint8_t *p=data;size_t initial=size;
    while(size && running) {
        struct pollfd fd={STDIN_FILENO,POLLIN,0};int r=poll(&fd,1,100);
        if(r<0 && errno==EINTR)continue;
        if(r<0)return -1;
        if(!r)continue;
        ssize_t n=read(STDIN_FILENO,p,size);
        if(n<0 && errno==EINTR)continue;
        if(n==0)return size==initial?1:2;
        if(n<0)return -1;
        p+=n;size-=(size_t)n;
    }
    return size ? -1 : 0;
}
static void *ingest(void *unused) {
    (void)unused;uint8_t h[24],pcm[AP2_MAX_FRAMES*4];
    while(running) {
        /* EOF is normal cancellation; a malformed complete message is a failure. */
        int read_result=read_all(h,sizeof(h));
        if(read_result){if(running && read_result!=1)input_error=1;break;}
        uint32_t type=ap2_get32(h+4),n=ap2_get32(h+8);
        if(ap2_get32(h)!=AP2_MAGIC || ap2_get32(h+12) ||
           (type!=AP2_AUDIO && type!=AP2_FLUSH) ||
           (type==AP2_AUDIO && (!n || n>AP2_MAX_FRAMES)) ||
           (type==AP2_FLUSH && n)) {input_error=1;break;}
        if(type==AP2_AUDIO && read_all(pcm,n*4)){input_error=1;break;}
        pthread_mutex_lock(&mutex);
        if(type==AP2_FLUSH)ap2_timeline_flush(&queue);
        else if(ap2_timeline_push(&queue,pcm,n,ap2_get64(h+16)))input_error=1;
        else received+=n;
        pthread_mutex_unlock(&mutex);
        if(input_error)break;
    }
    running=false;return NULL;
}
int main(int argc,char **argv) {
    if(argc!=7){fprintf(stderr,"usage: worker helper.json local_ip receiver_url uuid volume muted\n");return 2;}
    char *end;long volume=strtol(argv[5],&end,10);if(*end||volume<0||volume>100)return 2;
    long muted=strtol(argv[6],&end,10);if(*end||(muted!=0&&muted!=1))return 2;
    signal(SIGTERM,stop);signal(SIGINT,stop);signal(SIGPIPE,SIG_IGN);
    setvbuf(stdout,NULL,_IOLBF,0);
    if(strlen(argv[1])>=sizeof(glNativeHelperConfig))return 2;
    strcpy(glNativeHelperConfig,argv[1]);
    if(sonos_native_load_helper()){fprintf(stderr,"ap2 worker: could not load helper configuration\n");return 3;}
    struct sonos_native_device *device=sonos_native_device_new(argv[2],argv[3],argv[4],(int)muted);
    if(!device){fprintf(stderr,"ap2 worker: invalid receiver configuration\n");return 4;}
    sonos_native_volume(device,(int)volume);
    raop_pcm_output_t out=sonos_native_output(device);
    void *session=out.open(out.owner,&running);
    if(!session){char error[192];sonos_native_get_error(device,error,sizeof(error));fprintf(stderr,"ap2 worker: could not open receiver: %s\n",error);sonos_native_device_free(device);return 5;}
    uint8_t pcm[1004]={0};uint64_t start=now_ns(),report=start;int ready=0,rc=0;
    /* The sender's first submission establishes its clock; match its 75 ms lead. */
    ap2_timeline_init(&queue,start+75000000);
    pthread_t reader;
    if(pthread_create(&reader,NULL,ingest,NULL)){out.close(session);sonos_native_device_free(device);return 6;}
    while(running) {
        pthread_mutex_lock(&mutex);ap2_timeline_render(&queue,pcm,251);pthread_mutex_unlock(&mutex);
        if(out.write(session,pcm,sizeof(pcm))){rc=7;break;}
        if(!ready && sonos_native_session_ready(session)) {ready=1;puts("READY");}
        uint64_t now=now_ns();
        if(!ready && now-start>20000000000ULL){rc=8;break;}
        if(now-report>=5000000000ULL) {
            pthread_mutex_lock(&mutex);
            fprintf(stderr,"ap2 PCM received=%llu late=%llu silence=%llu realignments=%llu\n",
                (unsigned long long)received,(unsigned long long)queue.late_frames,
                (unsigned long long)queue.silence_frames,(unsigned long long)queue.realignments);
            pthread_mutex_unlock(&mutex);report=now;
        }
    }
    running=false;pthread_join(reader,NULL);
    if(input_error)rc=9;
    if(rc){char error[192];sonos_native_get_error(device,error,sizeof(error));fprintf(stderr,"ap2 worker failed rc=%d: %s\n",rc,error);}
    out.close(session);sonos_native_device_free(device);
    fprintf(stderr,"ap2 worker closed rc=%d received=%llu late=%llu silence=%llu realignments=%llu\n",rc,
        (unsigned long long)received,(unsigned long long)queue.late_frames,
        (unsigned long long)queue.silence_frames,(unsigned long long)queue.realignments);
    return rc;
}
