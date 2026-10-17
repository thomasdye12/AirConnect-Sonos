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
    assert(sonos_clock_reply(reply,48,request,48,500000,750000));
    const uint8_t half[]={0x83,0xaa,0x7e,0x80,0x80,0,0,0};
    const uint8_t three_quarters[]={0x83,0xaa,0x7e,0x80,0xc0,0,0,0};
    assert(!memcmp(reply+32,half,8));assert(!memcmp(reply+40,three_quarters,8));
    assert(!memcmp(reply+24,"abcdefgh",8));
    /* Independent decoding: every microsecond, including a second rollover,
     * must advance by approximately 4295 binary-fraction units, not 46 ms. */
    uint64_t previous=0;
    for(uint64_t us=999990;us<=1000010;us++) {
        assert(sonos_clock_reply(reply,48,request,48,us,us));
        uint64_t stamp=0;for(size_t j=32;j<40;j++)stamp=(stamp<<8)|reply[j];
        if(previous)assert(stamp-previous>=4294 && stamp-previous<=4295);
        previous=stamp;
    }
    assert(!sonos_clock_reply(reply,47,request,48,0,0));
    request[0]=0;assert(!sonos_clock_reply(reply,48,request,48,0,0));
    return 0;
}
