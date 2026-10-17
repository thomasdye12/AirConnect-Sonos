#define _POSIX_C_SOURCE 200809L
#include "sonos_sender.h"
#include "sonos_packet.h"
#include <arpa/inet.h>
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>
struct capture {int socket;uint8_t pcm[1004*20];};
static void pause_ms(long ms) {struct timespec t={ms/1000,(ms%1000)*1000000};while(nanosleep(&t,&t)&&errno==EINTR){}}
static uint64_t packet_timestamp(int rx,uint16_t expected) {
    uint8_t packet[1032],pcm[1004];uint32_t seq;uint64_t ts;uint32_t pos;
    ssize_t n=recv(rx,packet,sizeof(packet),0);assert(n>0);
    assert(sonos_packet_decode(packet,(size_t)n,&seq,&ts,&pos,pcm,sizeof(pcm)));
    assert(seq==SONOS_INITIAL_SEQUENCE+expected && pos==(uint32_t)expected*1004);return ts;
}
static void test_recovery(int rx) {
    struct sockaddr_in a; socklen_t len=sizeof(a);assert(!getsockname(rx,(struct sockaddr*)&a,&len));
    uint8_t pcm[1004]={0};
    for(int recovery=0;recovery<=1;++recovery) {
        struct sonos_sender *s=sonos_sender_open("127.0.0.1","127.0.0.1",ntohs(a.sin_port),0,75000);assert(s);
        if(recovery)sonos_sender_live_recovery(s,500000);
        assert(!sonos_sender_write(s,pcm,sizeof(pcm)));uint64_t first=packet_timestamp(rx,0);
        pause_ms(350);
        int rc=sonos_sender_write(s,pcm,sizeof(pcm));
        if(!recovery){assert(rc==-1 && errno==ETIMEDOUT);}
        else {
            assert(!rc);uint64_t resumed=packet_timestamp(rx,1);assert(resumed>first+300000);
            assert(sonos_sender_recoveries(s)==1);
            assert(!sonos_sender_write(s,pcm,sizeof(pcm)));uint64_t next=packet_timestamp(rx,2);
            assert(next-resumed>=5691 && next-resumed<=5692);
            pause_ms(700);assert(sonos_sender_write(s,pcm,sizeof(pcm))==-1 && errno==ETIMEDOUT);
        }
        sonos_sender_close(s);
    }
}
static void *receive_audio(void *arg) {
    struct capture *c=arg;
    for(int i=0;i<20;i++) {
        uint8_t packet[1032],pcm[1004];uint32_t seq;uint64_t ts;uint32_t pos;
        ssize_t n=recv(c->socket,packet,sizeof(packet),0);assert(n>=28);
        assert(sonos_packet_decode(packet,(size_t)n,&seq,&ts,&pos,pcm,sizeof(pcm)));
        assert(seq==SONOS_INITIAL_SEQUENCE+(uint32_t)i && pos==(uint32_t)i*1004);
        assert(!memcmp(pcm,c->pcm+i*1004,1004));
    }
    return 0;
}
int main(int argc,char **argv) {
    int rx=socket(AF_INET,SOCK_DGRAM,0),ntp=socket(AF_INET,SOCK_DGRAM,0);assert(rx>=0 && ntp>=0);
    struct sockaddr_in a={0};a.sin_family=AF_INET;assert(inet_pton(AF_INET,"127.0.0.1",&a.sin_addr)==1);
    assert(!bind(rx,(struct sockaddr*)&a,sizeof(a)));socklen_t len=sizeof(a);
    assert(!getsockname(rx,(struct sockaddr*)&a,&len));
    struct timeval timeout={2,0};assert(!setsockopt(rx,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout)));
    assert(!setsockopt(ntp,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout)));
    struct sonos_sender *s=sonos_sender_open("127.0.0.1","127.0.0.1",ntohs(a.sin_port),0,75000);assert(s);
    a.sin_port=htons(sonos_sender_clock_port(s));uint8_t req[48]={0},reply[48];
    req[0]=0x1b;memcpy(req+40,"testtime",8);
    assert(sendto(ntp,req,48,0,(struct sockaddr*)&a,sizeof(a))==48);
    assert(recv(ntp,reply,48,0)==48);assert(!memcmp(reply+24,"testtime",8));
    if(argc==2 && !strcmp(argv[1],"--long")) {
        /* Real sender pacing: cross the six-minute boundary with no test-only
         * counter setter or alternate packet generation path. */
        uint8_t pcm[1004]={0};
        for(uint32_t i=0;i<65540;i++) {
            assert(!sonos_sender_write(s,pcm,sizeof(pcm)));
            uint8_t packet[1032];ssize_t n=recv(rx,packet,sizeof(packet),0);assert(n>=28);
            uint32_t id=((uint32_t)packet[0]<<24)|((uint32_t)packet[1]<<16)|((uint32_t)packet[2]<<8)|packet[3];
            assert(id==SONOS_INITIAL_SEQUENCE+i);
        }
        struct sonos_sender_stats stats;sonos_sender_get_stats(s,&stats);
        assert(stats.packets==65540);sonos_sender_close(s);close(rx);close(ntp);return 0;
    }
    struct capture c={.socket=rx};
    for(size_t i=0;i<sizeof(c.pcm);i++)c.pcm[i]=(uint8_t)(i*17);
    pthread_t t;assert(!pthread_create(&t,0,receive_audio,&c));
    /* Deliberately split writes mid-sample and mid-packet. */
    size_t offset=0;
    while(offset<sizeof(c.pcm)) {
        size_t n=137;if(n>sizeof(c.pcm)-offset)n=sizeof(c.pcm)-offset;
        assert(!sonos_sender_write(s,c.pcm+offset,n));offset+=n;
    }
    assert(!pthread_join(t,0));struct sonos_sender_stats stats;
    sonos_sender_get_stats(s,&stats);assert(stats.packets==20 && stats.clock_requests==1);
    sonos_sender_close(s);test_recovery(rx);close(rx);close(ntp);
    assert(!sonos_sender_open("invalid","127.0.0.1",7020,0,75000));
    return 0;
}
