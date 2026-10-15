#include "timeline.h"
#include "protocol.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static struct ap2_timeline q;
static uint8_t input[AP2_MAX_FRAMES*4],output[AP2_MAX_FRAMES*4];
static uint64_t time_at(uint64_t epoch,int64_t frames){return epoch+(frames*1000000000LL+22050)/44100;}
int main(void) {
    const uint64_t epoch=100000000000ULL;memset(input,0x35,sizeof(input));
    ap2_timeline_init(&q,epoch);
    assert(!ap2_timeline_push(&q,input,352,time_at(epoch,441)));
    ap2_timeline_render(&q,output,441);
    for(int i=0;i<441*4;i++)assert(output[i]==0);
    ap2_timeline_render(&q,output,352);assert(!memcmp(input,output,352*4));
    /* Jitter within 20 ms must not add a zero block between contiguous audio. */
    assert(!ap2_timeline_push(&q,input,352,time_at(epoch,793)+5000000));
    ap2_timeline_render(&q,output,352);assert(!memcmp(input,output,352*4));
    assert(q.silence_frames==441);
    /* Flush removes future audio and old alignment; resume can use a new epoch. */
    assert(!ap2_timeline_push(&q,input,352,time_at(epoch,1145)));
    ap2_timeline_flush(&q);ap2_timeline_render(&q,output,352);
    for(int i=0;i<352*4;i++)assert(output[i]==0);
    assert(!ap2_timeline_push(&q,input,352,time_at(epoch,1497)));
    ap2_timeline_render(&q,output,352);assert(!memcmp(input,output,352*4));
    ap2_timeline_flush(&q);
    assert(!ap2_timeline_push(&q,input,100,time_at(epoch,0)));assert(q.late_frames==100);
    assert(ap2_timeline_push(&q,input,100,time_at(epoch,q.cursor+AP2_CAPACITY))==-1);
    assert(ap2_timeline_push(&q,input,AP2_MAX_FRAMES+1,epoch)==-1);
    assert(ap2_timeline_push(&q,input,10,UINT64_MAX)==-1);
    /* A new timeline must not leak previously queued audio after a seek. */
    ap2_timeline_init(&q,epoch);
    assert(!ap2_timeline_push(&q,input,352,time_at(epoch,4410)));
    assert(!ap2_timeline_push(&q,input,100,epoch));
    ap2_timeline_render(&q,output,100);assert(!memcmp(input,output,400));
    ap2_timeline_render(&q,output,4096);ap2_timeline_render(&q,output,566);
    for(int i=0;i<566*4;i++)assert(output[i]==0);
    assert(q.realignments==1);
    /* Exercise ring wrap, including adjacent blocks of differing packet size. */
    ap2_timeline_init(&q,epoch);
    for(int j=0;j<600;j++) {
        size_t n=(j%2)?251:352;
        assert(!ap2_timeline_push(&q,input,n,time_at(epoch,q.cursor)));
        ap2_timeline_render(&q,output,n);assert(!memcmp(input,output,n*4));
    }
    assert(q.silence_frames==0 && q.realignments==0);
    uint8_t h[24]={0};ap2_put32(h,AP2_MAGIC);ap2_put64(h+16,epoch);
    assert(ap2_get32(h)==AP2_MAGIC && ap2_get64(h+16)==epoch);
    puts("AirPlay 2 timeline: deadlines, continuity, flush, late input, overflow and wrap passed");
}
