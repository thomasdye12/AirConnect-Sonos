#define _POSIX_C_SOURCE 200809L
#include "sonos_sender.h"
#include "sonos_packet.h"
#include <arpa/inet.h>
#include <errno.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>
struct sonos_sender {
    int audio,clock,stop;
    uint16_t clock_port;
    uint32_t sequence;
    uint32_t position,lead_us;
    uint32_t recovery_limit_us;
    uint64_t recoveries;
    uint64_t base_us,frames;
    size_t pending;
    uint8_t pcm[SONOS_PCM_BYTES];
    struct in_addr peer;
    pthread_t thread;
    pthread_mutex_t mutex;
    struct sonos_sender_stats stats;
};
static uint64_t now_us(void) {
    struct timespec ts;
    if(clock_gettime(CLOCK_MONOTONIC,&ts)) return 0;
    return (uint64_t)ts.tv_sec*1000000+(uint64_t)ts.tv_nsec/1000;
}
static int delay_until(uint64_t target) {
    uint64_t now;
    while((now=now_us())<target) {
        uint64_t gap=target-now;
        struct timespec ts={(time_t)(gap/1000000),(long)(gap%1000000)*1000};
        if(nanosleep(&ts,0) && errno!=EINTR) return -1;
    }
    return 0;
}
static void *clock_thread(void *arg) {
    struct sonos_sender *s=arg;
    for(;;) {
        pthread_mutex_lock(&s->mutex);int stop=s->stop;pthread_mutex_unlock(&s->mutex);
        if(stop)break;
        fd_set fds;FD_ZERO(&fds);FD_SET(s->clock,&fds);
        struct timeval timeout={0,100000};
        int n=select(s->clock+1,&fds,0,0,&timeout);
        if(n<0 && errno==EINTR)continue;
        if(n<0)break;
        if(!n)continue;
        uint8_t req[512],reply[48];struct sockaddr_in peer;socklen_t size=sizeof(peer);
        ssize_t got=recvfrom(s->clock,req,sizeof(req),0,(struct sockaddr*)&peer,&size);
        uint64_t received=now_us();
        if(got!=48 || peer.sin_addr.s_addr!=s->peer.s_addr)continue;
        if(!sonos_clock_reply(reply,sizeof(reply),req,(size_t)got,received,now_us()))continue;
        if(sendto(s->clock,reply,sizeof(reply),0,(struct sockaddr*)&peer,size)==48) {
            pthread_mutex_lock(&s->mutex);++s->stats.clock_requests;pthread_mutex_unlock(&s->mutex);
        }
    }
    return 0;
}
struct sonos_sender *sonos_sender_open(const char *local,const char *peer,uint16_t aport,uint16_t cport,uint32_t lead) {
    if(!local || !peer || !aport || lead>1000000) {errno=EINVAL;return 0;}
    struct sockaddr_in l={0},p={0};l.sin_family=p.sin_family=AF_INET;
    if(inet_pton(AF_INET,local,&l.sin_addr)!=1 || inet_pton(AF_INET,peer,&p.sin_addr)!=1) {errno=EINVAL;return 0;}
    struct sonos_sender *s=calloc(1,sizeof(*s));if(!s)return 0;
    s->sequence=SONOS_INITIAL_SEQUENCE;
    s->audio=s->clock=-1;s->peer=p.sin_addr;s->lead_us=lead;
    int e=pthread_mutex_init(&s->mutex,0);if(e){free(s);errno=e;return 0;}
    s->audio=socket(AF_INET,SOCK_DGRAM,0);if(s->audio<0)goto fail;
    if(bind(s->audio,(struct sockaddr*)&l,sizeof(l)))goto fail;
    p.sin_port=htons(aport);if(connect(s->audio,(struct sockaddr*)&p,sizeof(p)))goto fail;
    s->clock=socket(AF_INET,SOCK_DGRAM,0);if(s->clock<0)goto fail;
    if(s->clock>=FD_SETSIZE){errno=EMFILE;goto fail;}
    l.sin_port=htons(cport);if(bind(s->clock,(struct sockaddr*)&l,sizeof(l)))goto fail;
    socklen_t size=sizeof(l);if(getsockname(s->clock,(struct sockaddr*)&l,&size))goto fail;
    s->clock_port=ntohs(l.sin_port);
    e=pthread_create(&s->thread,0,clock_thread,s);if(e){errno=e;goto fail;}
    return s;
fail:
    e=errno;if(s->audio>=0)close(s->audio);if(s->clock>=0)close(s->clock);
    pthread_mutex_destroy(&s->mutex);free(s);errno=e;return 0;
}
uint16_t sonos_sender_clock_port(struct sonos_sender *s) {return s?s->clock_port:0;}
void sonos_sender_live_recovery(struct sonos_sender *s,uint32_t limit) {if(s)s->recovery_limit_us=limit>2000000?2000000:limit;}
uint64_t sonos_sender_recoveries(struct sonos_sender *s) {return s?s->recoveries:0;}
int sonos_sender_write(struct sonos_sender *s,const uint8_t *pcm,size_t n) {
    if(!s || (!pcm && n)){errno=EINVAL;return -1;}
    while(n) {
        size_t take=SONOS_PCM_BYTES-s->pending;if(take>n)take=n;
        memcpy(s->pcm+s->pending,pcm,take);s->pending+=take;pcm+=take;n-=take;
        if(s->pending<SONOS_PCM_BYTES)continue;
        if(!s->base_us)s->base_us=now_us();
        uint64_t deadline=s->base_us+s->frames*1000000/44100;
        if(delay_until(deadline))return -1;
        uint64_t now=now_us();
        /* Long producer stalls need explicit session recovery; never burst old
         * audio with expired timestamps into a receiver. */
        if(now>deadline+250000) {
            if(!s->recovery_limit_us || now-deadline>s->recovery_limit_us){errno=ETIMEDOUT;return -1;}
            s->base_us+=now-deadline;deadline=now;++s->recoveries;
        }
        uint8_t packet[SONOS_PACKET_BYTES];
        size_t length=sonos_packet_encode(packet,sizeof(packet),s->sequence,
            deadline+s->lead_us,s->position,s->pcm,sizeof(s->pcm));
        if(!length){errno=EINVAL;return -1;}
        ssize_t sent;
        do {sent=send(s->audio,packet,length,0);} while(sent<0 && errno==EINTR);
        if(sent!=(ssize_t)length)return -1;
        pthread_mutex_lock(&s->mutex);
        ++s->stats.packets;if(now>deadline+6000)++s->stats.late_packets;
        pthread_mutex_unlock(&s->mutex);
        ++s->sequence;s->position+=SONOS_PCM_BYTES;s->frames+=251;s->pending=0;
    }
    return 0;
}
void sonos_sender_get_stats(struct sonos_sender *s,struct sonos_sender_stats *stats) {
    if(!s || !stats)return;
    pthread_mutex_lock(&s->mutex);*stats=s->stats;pthread_mutex_unlock(&s->mutex);
}
void sonos_sender_close(struct sonos_sender *s) {
    if(!s)return;
    pthread_mutex_lock(&s->mutex);s->stop=1;pthread_mutex_unlock(&s->mutex);
    pthread_join(s->thread,0);close(s->audio);close(s->clock);
    pthread_mutex_destroy(&s->mutex);free(s);
}
