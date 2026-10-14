#define _POSIX_C_SOURCE 200809L
#include "sonos_sender.h"
#include "sonos_packet.h"
#include <arpa/inet.h>
#include <assert.h>
#include <pthread.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>
struct capture {int socket;uint8_t pcm[1004*20];};
static void *receive_audio(void *arg) {
    struct capture *c=arg;
    for(int i=0;i<20;i++) {
        uint8_t packet[1032],pcm[1004];uint16_t seq;uint64_t ts;uint32_t pos;
        ssize_t n=recv(c->socket,packet,sizeof(packet),0);assert(n>=28);
        assert(sonos_packet_decode(packet,(size_t)n,&seq,&ts,&pos,pcm,sizeof(pcm)));
        assert(seq==i && pos==(uint32_t)i*1004);
        assert(!memcmp(pcm,c->pcm+i*1004,1004));
    }
    return 0;
}
int main(void) {
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
    sonos_sender_close(s);close(rx);close(ntp);
    assert(!sonos_sender_open("invalid","127.0.0.1",7020,0,75000));
    return 0;
}
