#include "timeline.h"
#include <limits.h>
#include <string.h>
void ap2_timeline_flush(struct ap2_timeline *q) {
    for (size_t i=0;i<AP2_CAPACITY;i++) q->tags[i]=-1;
    q->aligned=0;
}
void ap2_timeline_init(struct ap2_timeline *q,uint64_t epoch_ns) {
    memset(q,0,sizeof(*q));q->epoch_ns=epoch_ns;ap2_timeline_flush(q);
}
int ap2_timeline_push(struct ap2_timeline *q,const uint8_t *pcm,size_t frames,uint64_t when_ns) {
    if(!pcm || !frames || frames>AP2_MAX_FRAMES)return -1;
    /* Bound arithmetic before converting nanoseconds to sample positions. */
    uint64_t distance=when_ns>=q->epoch_ns?when_ns-q->epoch_ns:q->epoch_ns-when_ns;
    if(distance>UINT64_C(86400000000000))return -1;
    int64_t ns=when_ns>=q->epoch_ns?(int64_t)distance:-(int64_t)distance;
    int64_t scaled=ns*AP2_RATE;
    int64_t start=(scaled+(scaled>=0?500000000:-500000000))/INT64_C(1000000000);
    int64_t drift=start-q->next_input;
    /* Small timing noise cannot insert gaps into otherwise contiguous PCM. */
    if(q->aligned && drift>=-882 && drift<=882)start=q->next_input;
    int realign=q->aligned && (drift < -882 || drift > 882);
    if(start+(int64_t)frames>q->cursor+AP2_CAPACITY)return -1;
    if(realign){ap2_timeline_flush(q);q->realignments++;}
    for(size_t i=0;i<frames;i++) {
        int64_t at=start+(int64_t)i;
        if(at<q->cursor){q->late_frames++;continue;}
        size_t slot=(size_t)(at%AP2_CAPACITY);
        if(q->tags[slot]>=q->cursor && q->tags[slot]!=at)return -1;
    }
    for(size_t i=0;i<frames;i++) {
        int64_t at=start+(int64_t)i;if(at<q->cursor)continue;
        size_t slot=(size_t)(at%AP2_CAPACITY);
        memcpy(q->pcm+slot*4,pcm+i*4,4);q->tags[slot]=at;
    }
    q->next_input=start+(int64_t)frames;q->aligned=1;return 0;
}
void ap2_timeline_render(struct ap2_timeline *q,uint8_t *pcm,size_t frames) {
    for(size_t i=0;i<frames;i++,q->cursor++) {
        size_t slot=(size_t)(q->cursor%AP2_CAPACITY);
        if(q->tags[slot]==q->cursor)memcpy(pcm+i*4,q->pcm+slot*4,4);
        else {memset(pcm+i*4,0,4);q->silence_frames++;}
        q->tags[slot]=-1;
    }
}
