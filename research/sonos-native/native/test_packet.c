#include "sonos_packet.h"
#include <assert.h>
#include <string.h>
int main(void) {
    uint8_t pcm[1004], decoded[1004], packet[1032], request[48]={0}, reply[48];
    uint16_t seq;uint64_t us;uint32_t pos;
    for(size_t zeroes=0;zeroes<=1004;++zeroes) {
        memset(pcm,0x35,sizeof(pcm));memset(pcm+1004-zeroes,0,zeroes);
        size_t n=sonos_packet_encode(packet,sizeof(packet),65535,123456789,400,pcm,sizeof(pcm));
        assert(n==1032-zeroes);
        assert(sonos_packet_decode(packet,n,&seq,&us,&pos,decoded,sizeof(decoded)));
        assert(seq==65535 && us==123456789 && pos==400 && !memcmp(pcm,decoded,1004));
    }
    assert(!sonos_packet_encode(packet,27,0,0,0,pcm,1004));
    assert(!sonos_packet_decode(packet,27,&seq,&us,&pos,decoded,1004));
    assert(!sonos_packet_decode(packet,1033,&seq,&us,&pos,decoded,1004));
    request[0]=0x1b;memcpy(request+40,"abcdefgh",8);
    assert(sonos_clock_reply(reply,48,request,48,1896563975895,1896563976219));
    const uint8_t expected[]={0x83,0xc7,0x6e,0xf3,0xee,0x41,0x70,0x00};
    assert(!memcmp(reply+32,expected,8));assert(!memcmp(reply+24,"abcdefgh",8));
    assert(!sonos_clock_reply(reply,47,request,48,0,0));
    request[0]=0;assert(!sonos_clock_reply(reply,48,request,48,0,0));
    return 0;
}
