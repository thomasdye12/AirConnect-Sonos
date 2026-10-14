/* Verify the PCM boundary, byte order, lock ownership, FLUSH and close ordering. */
#include <assert.h>
#define gettime_ms test_clock_ms
#include "../common/libraop/src/raop_streamer.c"
static int fake_clock_enabled;
static uint32_t fake_clock;
uint32_t test_clock_ms(void) {return fake_clock_enabled ? fake_clock : gettime_us()/1000;}
log_level raop_loglevel=lERROR, util_loglevel=lERROR;
struct sink {
    raopst_t *stream;
    pthread_mutex_t mutex;
    int opens, writes, signals, zeros, closes, fail_after;
};
static void *sink_open(void *owner, const volatile bool *running) {
    assert(*running);
    struct sink *s=owner;
    assert(!pthread_mutex_trylock(&s->stream->ab_mutex));pthread_mutex_unlock(&s->stream->ab_mutex);
    pthread_mutex_lock(&s->mutex);s->opens++;pthread_mutex_unlock(&s->mutex);return s;
}
static int sink_write(void *ctx,const uint8_t *pcm,size_t bytes) {
    struct sink *s=ctx;
    assert(!pthread_mutex_trylock(&s->stream->ab_mutex));pthread_mutex_unlock(&s->stream->ab_mutex);
    assert(bytes==352*4);
    int nonzero=0;
    for(size_t i=0;i<bytes;i+=4) {
        if(pcm[i]||pcm[i+1]||pcm[i+2]||pcm[i+3]) {
            assert(pcm[i]==0x34 && pcm[i+1]==0x12 && pcm[i+2]==0xcc && pcm[i+3]==0xed);
            nonzero=1;
        }
    }
    pthread_mutex_lock(&s->mutex);s->writes++;s->signals+=nonzero;s->zeros+=!nonzero;
    int fail=s->fail_after && s->writes>=s->fail_after;pthread_mutex_unlock(&s->mutex);
    usleep(7982);return fail?-1:0;
}
static void sink_close(void *ctx) {
    struct sink *s=ctx;
    assert(!pthread_mutex_trylock(&s->stream->ab_mutex));pthread_mutex_unlock(&s->stream->ab_mutex);
    pthread_mutex_lock(&s->mutex);s->closes++;pthread_mutex_unlock(&s->mutex);
}
static int counter(struct sink *s,int which) {
    pthread_mutex_lock(&s->mutex);int n=which==0?s->writes:which==1?s->signals:which==2?s->zeros:s->closes;pthread_mutex_unlock(&s->mutex);return n;
}
static void wait_count(struct sink *s,int which,int target) {
    for(int n=0;n<1000 && counter(s,which)<target;++n)usleep(1000);
    assert(counter(s,which)>=target);
}
static void fill(raopst_t *ctx,int first) {
    pthread_mutex_lock(&ctx->ab_mutex);
    ctx->state=RTP_PLAY;ctx->synchro.status=RTP_SYNC|NTP_SYNC;ctx->pcm_aligned=false;
    ctx->synchro.time=gettime_ms();ctx->synchro.rtp=first*352;
    ctx->ab_read=first;ctx->ab_write=first+49;
    for(int i=first;i<=first+49;++i) {
        abuf_t *frame=&ctx->audio_buffer[BUFIDX(i)];frame->ready=1;frame->len=352*4;frame->rtptime=i*352;
        for(int j=0;j<352;++j){frame->data[j*2]=0x1234;frame->data[j*2+1]=-0x1234;}
    }
    pthread_mutex_unlock(&ctx->ab_mutex);
}
static void exercise(int failure) {
    raopst_t ctx={0};struct sink s={0};s.stream=&ctx;s.fail_after=failure?12:0;
    pthread_mutex_init(&s.mutex,NULL);pthread_mutex_init(&ctx.ab_mutex,NULL);
    ctx.frame_size=352;ctx.running=true;ctx.first_seqno=-1;ctx.ab_read=1;
    ctx.silence_frame=calloc(352,4);buffer_alloc(ctx.audio_buffer,352*4);
    ctx.encoder=encoder_create("flac",44100,2,2,0,&ctx.icy.interval);
    ctx.pcm=(raop_pcm_output_t){&s,sink_open,sink_write,sink_close};
    fill(&ctx,100);
    pthread_t thread;assert(!pthread_create(&thread,NULL,pcm_thread_func,&ctx));
    wait_count(&s,1,4);
    if(!failure) {
        int before_flush=counter(&s,1);
        assert(raopst_flush(&ctx,1000,352000,false,false));
        int zeros=counter(&s,2);wait_count(&s,2,zeros+5);
        /* Only one block already copied outside the ingest mutex may finish. */
        assert(counter(&s,1)<=before_flush+1);
        int signals=counter(&s,1);fill(&ctx,1000);wait_count(&s,1,signals+5);
    } else wait_count(&s,3,1);
    ctx.running=false;pthread_join(thread,NULL);
    assert(s.opens==1 && s.closes==1 && s.signals>0);
    encoder_delete(ctx.encoder);buffer_release(ctx.audio_buffer);free(ctx.silence_frame);
    pthread_mutex_destroy(&ctx.ab_mutex);pthread_mutex_destroy(&s.mutex);
}
static void timing(void) {
    raopst_t ctx={0}; size_t bytes=0;
    pthread_mutex_init(&ctx.ab_mutex,NULL);
    ctx.frame_size=352;ctx.pcm.open=sink_open;ctx.pcm.lead_ms=75;
    buffer_alloc(ctx.audio_buffer,352*4);
    fill(&ctx,100);
    ctx.synchro.time=gettime_ms()+600;
    assert(!_buffer_get_frame(&ctx,&bytes));
    assert(ctx.ab_read==100 && ctx.audio_buffer[BUFIDX(100)].ready);
    /* More than 32 future packets must survive a queued native setup. */
    assert(ctx.ab_write-ctx.ab_read+1==50);
    ctx.synchro.time=gettime_ms();ctx.pcm.sync_offset_ms=500;
    assert(!_buffer_get_frame(&ctx,&bytes) && ctx.ab_read==100);
    ctx.pcm.sync_offset_ms=0;
    ctx.synchro.time=gettime_ms()+75;
    assert(_buffer_get_frame(&ctx,&bytes) && ctx.ab_read==101);
    fill(&ctx,100);
    ctx.synchro.time=gettime_ms()-100;
    assert(_buffer_get_frame(&ctx,&bytes));
    assert(ctx.ab_read>=121 && ctx.ab_read<=123);
    /* A distant/wrapped RTP timestamp must not overflow sample-to-ms math. */
    ctx.synchro.time=1000;ctx.synchro.rtp=0xfffffff0;
    assert(frame_playtime(&ctx,ctx.synchro.rtp+44100*100)==101000);
    assert(frame_playtime(&ctx,ctx.synchro.rtp-44100)==0);
    buffer_release(ctx.audio_buffer);pthread_mutex_destroy(&ctx.ab_mutex);
}
static void discontinuity(void) {
    raopst_t ctx={0};size_t bytes=0;
    pthread_mutex_init(&ctx.ab_mutex,NULL);ctx.frame_size=352;
    buffer_alloc(ctx.audio_buffer,352*4);fill(&ctx,100);
    ctx.pcm.open=sink_open;ctx.pcm.lead_ms=75;
    ctx.pcm_clock_ready=true;ctx.pcm_clock_base=10000;ctx.pcm_aligned=true;
    ctx.synchro.time=10175;
    assert(!_buffer_get_frame(&ctx,&bytes));
    assert(!ctx.pcm_aligned && ctx.pcm_realignments==1 && ctx.ab_read==100);
    ctx.pcm_samples=4410;
    assert(_buffer_get_frame(&ctx,&bytes) && ctx.ab_read==101 && ctx.pcm_aligned);
    ctx.synchro.time-=100;
    assert(_buffer_get_frame(&ctx,&bytes));
    assert(ctx.pcm_realignments==2 && ctx.pcm_dropped_frames>0);
    buffer_release(ctx.audio_buffer);pthread_mutex_destroy(&ctx.ab_mutex);
}
static void future_thread(void) {
    raopst_t ctx={0};struct sink s={0};s.stream=&ctx;
    pthread_mutex_init(&s.mutex,NULL);pthread_mutex_init(&ctx.ab_mutex,NULL);
    ctx.frame_size=352;ctx.running=true;ctx.first_seqno=-1;
    ctx.silence_frame=calloc(352,4);buffer_alloc(ctx.audio_buffer,352*4);
    ctx.pcm=(raop_pcm_output_t){&s,sink_open,sink_write,sink_close,75};
    fill(&ctx,100);ctx.synchro.time=gettime_ms()+400;
    pthread_t thread;assert(!pthread_create(&thread,NULL,pcm_thread_func,&ctx));
    wait_count(&s,2,10);assert(counter(&s,1)==0);
    wait_count(&s,1,1);
    assert((int32_t)(gettime_ms()-ctx.synchro.time)>=-75);
    ctx.running=false;pthread_join(thread,NULL);assert(s.opens==1&&s.closes==1);
    buffer_release(ctx.audio_buffer);free(ctx.silence_frame);
    pthread_mutex_destroy(&ctx.ab_mutex);pthread_mutex_destroy(&s.mutex);
}
/* Model the real sender: 352-sample writes are split into 251-sample UDP
 * packets. write() returns at the last complete packet deadline, not at the
 * timestamp of the next input sample. Scheduler jitter must not alter PCM. */
struct continuity_sink {raopst_t *ctx;unsigned writes, zeros, jumps, samples;};
static void *continuity_open(void *owner,const volatile bool *running) {(void)running;return owner;}
static int continuity_write(void *owner,const uint8_t *pcm,size_t bytes) {
    struct continuity_sink *s=owner;
    for(size_t i=0;i<bytes;i+=4) {
        unsigned sample=pcm[i]|(pcm[i+1]<<8);
        unsigned expected=s->samples/352+1;
        if(!sample)s->zeros++;
        if(sample!=expected)s->jumps++;
        s->samples++;
    }
    s->writes++;
    unsigned sent_packets=s->samples/251;
    fake_clock=10000+(sent_packets?sent_packets-1:0)*251ULL*1000/44100;
    if(s->writes%7==0)fake_clock+=3;
    s->ctx->synchro.time=10075+(s->writes%9==0?2:0);
    if(s->writes==160)s->ctx->running=false;
    return 0;
}
static void continuity_close(void *owner) {(void)owner;}
static void continuity(void) {
    raopst_t ctx={0};struct continuity_sink s={.ctx=&ctx};
    pthread_mutex_init(&ctx.ab_mutex,NULL);ctx.frame_size=352;ctx.running=true;
    ctx.state=RTP_PLAY;ctx.synchro.status=RTP_SYNC|NTP_SYNC;
    ctx.synchro.time=10075;ctx.synchro.rtp=100*352;
    ctx.ab_read=100;ctx.ab_write=299;buffer_alloc(ctx.audio_buffer,352*4);
    ctx.pcm=(raop_pcm_output_t){&s,continuity_open,continuity_write,continuity_close,75,0};
    for(int i=100;i<=299;i++) {
        abuf_t *f=&ctx.audio_buffer[BUFIDX(i)];f->ready=1;f->len=352*4;f->rtptime=i*352;
        for(int j=0;j<704;j++)f->data[j]=i-99;
    }
    fake_clock_enabled=1;fake_clock=10000;pcm_thread_func(&ctx);fake_clock_enabled=0;
    printf("Native continuity: %u samples, %u unexpected zeros, %u changed samples\n",s.samples,s.zeros,s.jumps);
    fflush(stdout);assert(s.zeros==0 && s.jumps==0);
    buffer_release(ctx.audio_buffer);pthread_mutex_destroy(&ctx.ab_mutex);
}
int main(void){continuity();timing();discontinuity();future_thread();exercise(0);exercise(1);puts("PCM output: continuity, presentation timing, stale frames, RTP wrap, endian, flush/resume and close passed");return 0;}
