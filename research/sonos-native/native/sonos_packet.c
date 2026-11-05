#include "sonos_packet.h"
#include <string.h>
#include <limits.h>
static void put32(uint8_t *p, uint32_t x) {
    p[0]=(uint8_t)(x>>24); p[1]=(uint8_t)(x>>16); p[2]=(uint8_t)(x>>8); p[3]=(uint8_t)x;
}
static uint32_t get32(const uint8_t *p) {
    return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3];
}
size_t sonos_packet_encode(uint8_t *out, size_t cap, uint32_t seq,
                          uint64_t us, uint32_t pos, const uint8_t *pcm, size_t n) {
    static const uint8_t prefix[8]={3,0,0,0,1,0,3,0xf0};
    static const uint8_t format[4]={2,16,0xac,0x44};
    if (!out || !pcm || cap<SONOS_PACKET_BYTES || n!=SONOS_PCM_BYTES || us/1000000>UINT32_MAX) return 0;
    put32(out,seq);
    memcpy(out+4,prefix,sizeof(prefix)); put32(out+12,(uint32_t)(us/1000000));
    put32(out+16,(uint32_t)(us%1000000)); put32(out+20,pos);
    memcpy(out+24,format,sizeof(format)); memcpy(out+28,pcm,n);
    n=SONOS_PACKET_BYTES;
    while(n>28 && !out[n-1]) --n;
    return n;
}
int sonos_packet_decode(const uint8_t *p, size_t n, uint32_t *seq,
                        uint64_t *us, uint32_t *pos, uint8_t *pcm, size_t cap) {
    static const uint8_t prefix[8]={3,0,0,0,1,0,3,0xf0};
    static const uint8_t format[4]={2,16,0xac,0x44};
    if(!p || !seq || !us || !pos || !pcm || cap<SONOS_PCM_BYTES || n<28 || n>SONOS_PACKET_BYTES) return 0;
    if(memcmp(p+4,prefix,8) || memcmp(p+24,format,4) || get32(p+16)>=1000000) return 0;
    *seq=get32(p);
    *us=(uint64_t)get32(p+12)*1000000+get32(p+16); *pos=get32(p+20);
    memcpy(pcm,p+28,n-28); memset(pcm+n-28,0,SONOS_PCM_BYTES-(n-28));
    return 1;
}
static void clock_stamp(uint8_t *p,uint64_t us) {
    put32(p,(uint32_t)(us/1000000+UINT64_C(2208988800)));
    /* NTP uses a 32-bit fraction of one second. Shifting microseconds by 12
     * under-reports time by up to 46.3 ms, then jumps at each second boundary. */
    put32(p+4,(uint32_t)(((us%1000000)<<32)/1000000));
}
int sonos_clock_reply(uint8_t *out,size_t cap,const uint8_t *req,size_t n,
                      uint64_t received,uint64_t sent) {
    uint8_t origin[8];
    if(!out || !req || cap<48 || n!=48 || (req[0]&7)!=3) return 0;
    memcpy(origin,req+40,8); memset(out,0,48);
    out[0]=0x1c;out[1]=0x0f;out[2]=8;
    memcpy(out+24,origin,8);clock_stamp(out+32,received);clock_stamp(out+40,sent);
    return 1;
}
