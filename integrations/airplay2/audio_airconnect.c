/* AirConnect output backend for pinned Shairport Sync. MIT, repository LICENSE.
 * The child process isolates AirConnect's dependency symbols from Shairport.
 * No network socket or unauthenticated audio endpoint is created by this IPC. */
#include "audio.h"
#include "common.h"
#include "protocol.h"
#include "timeline.h"
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <spawn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
extern char **environ;
static const char *worker,*helper,*local_ip,*receiver_url,*receiver_udn;
static int volume=25,muted=1,fd=-1,status_fd=-1,failed;
static pid_t child=-1;
static pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;
static uint64_t mono_ns(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000+t.tv_nsec;}
static void finish_locked(void) {
    if(fd>=0){close(fd);fd=-1;}
    if(status_fd>=0){close(status_fd);status_fd=-1;}
    if(child>0) {
        uint64_t deadline=mono_ns()+35000000000ULL;int status,r;
        while((r=waitpid(child,&status,WNOHANG))==0 && mono_ns()<deadline) {
            struct timespec delay={0,100000000};nanosleep(&delay,NULL);
        }
        if(r>0 && WIFEXITED(status) && WEXITSTATUS(status))
            warn("AirConnect worker exited with status %d.",WEXITSTATUS(status));
        if(r>0 && WIFSIGNALED(status))
            warn("AirConnect worker terminated by signal %d.",WTERMSIG(status));
        if(r==0) {
            warn("AirConnect worker did not restore within deadline; terminating. Check speaker state.");
            kill(child,SIGTERM);deadline=mono_ns()+3000000000ULL;
            while((r=waitpid(child,&status,WNOHANG))==0 && mono_ns()<deadline){struct timespec t={0,100000000};nanosleep(&t,NULL);}
            if(r==0){kill(child,SIGKILL);waitpid(child,&status,0);}
        }
        child=-1;
    }
}
static int send_all(const void *data,size_t size) {
    const uint8_t *p=data;uint64_t deadline=mono_ns()+750000000;
    while(size) {
        ssize_t n=write(fd,p,size);
        if(n>0){p+=n;size-=(size_t)n;continue;}
        if(n<0 && errno==EINTR)continue;
        if(n<0 && (errno==EAGAIN||errno==EWOULDBLOCK) && mono_ns()<deadline) {
            struct pollfd f={fd,POLLOUT,0};poll(&f,1,20);continue;
        }
        failed=1;return -1;
    }
    return 0;
}
static int init(int argc,char **argv) {
    /* Pinned Shairport forwards CLI arguments here and ignores init's return
     * value. This config-only backend must initialise even when argc != 0. */
    (void)argc;(void)argv;
    if(!config.cfg || !config_lookup_string(config.cfg,"airconnect.worker",&worker) ||
       !config_lookup_string(config.cfg,"airconnect.helper",&helper) ||
       !config_lookup_string(config.cfg,"airconnect.local_ip",&local_ip) ||
       !config_lookup_string(config.cfg,"airconnect.receiver_url",&receiver_url) ||
       !config_lookup_string(config.cfg,"airconnect.receiver_udn",&receiver_udn))
        die("AirConnect backend requires worker, helper, local_ip, receiver_url and receiver_udn.");
    config_lookup_int(config.cfg,"airconnect.speaker_volume",&volume);
    config_lookup_bool(config.cfg,"airconnect.muted",&muted);
    if(worker[0]!='/' || helper[0]!='/' || volume<0 || volume>100)die("Invalid AirConnect configuration.");
    config.audio_backend_buffer_desired_length=0.2;
    config.audio_backend_latency_offset=0;
    signal(SIGPIPE,SIG_IGN);
    return 0;
}
static int prepare(void) {
    int cancellation;pthread_setcancelstate(PTHREAD_CANCEL_DISABLE,&cancellation);
    pthread_mutex_lock(&lock);finish_locked();failed=0;
    int input[2]={-1,-1},output[2]={-1,-1};
    if(pipe(input)||pipe(output))goto bad;
    for(int i=0;i<2;i++){fcntl(input[i],F_SETFD,FD_CLOEXEC);fcntl(output[i],F_SETFD,FD_CLOEXEC);}
    posix_spawn_file_actions_t actions;posix_spawn_file_actions_init(&actions);
    posix_spawn_file_actions_adddup2(&actions,input[0],STDIN_FILENO);
    posix_spawn_file_actions_adddup2(&actions,output[1],STDOUT_FILENO);
    posix_spawn_file_actions_addclose(&actions,input[1]);
    posix_spawn_file_actions_addclose(&actions,output[0]);
    char vol[8],mute[4];snprintf(vol,sizeof(vol),"%d",volume);snprintf(mute,sizeof(mute),"%d",muted);
    char *args[]={(char*)worker,(char*)helper,(char*)local_ip,(char*)receiver_url,(char*)receiver_udn,vol,mute,NULL};
    int rc=posix_spawn(&child,worker,&actions,NULL,args,environ);
    posix_spawn_file_actions_destroy(&actions);
    if(rc){warn("AirConnect worker could not start: %s.",strerror(rc));child=-1;goto bad;}
    close(input[0]);input[0]=-1;close(output[1]);output[1]=-1;
    fd=input[1];input[1]=-1;status_fd=output[0];output[0]=-1;
    fcntl(fd,F_SETFL,fcntl(fd,F_GETFL)|O_NONBLOCK);
    char response[64];size_t used=0;uint64_t deadline=mono_ns()+45000000000ULL;
    while(mono_ns()<deadline && used<sizeof(response)-1) {
        struct pollfd f={status_fd,POLLIN,0};int r=poll(&f,1,100);
        if(r<0 && errno==EINTR)continue;
        if(r<0)break;
        if(!r)continue;
        ssize_t n=read(status_fd,response+used,1);
        if(n<=0)break;
        if(response[used++]=='\n') {
            response[used]=0;
            if(!strcmp(response,"READY\n")) {debug(1,"AirConnect receiver ready.");pthread_mutex_unlock(&lock);pthread_setcancelstate(cancellation,NULL);return 0;}
            used=0;
        }
    }
 bad:
    for(int i=0;i<2;i++){if(input[i]>=0)close(input[i]);if(output[i]>=0)close(output[i]);}
    failed=1;finish_locked();pthread_mutex_unlock(&lock);pthread_setcancelstate(cancellation,NULL);
    die("AirConnect receiver preparation failed; see worker log.");return -1;
}
static int32_t get_configuration(unsigned int channels,unsigned int rate,unsigned int format) {
    (void)channels;(void)rate;(void)format;
    return CHANNELS_TO_ENCODED_FORMAT(2)|RATE_TO_ENCODED_FORMAT(AP2_RATE)|FORMAT_TO_ENCODED_FORMAT(SPS_FORMAT_S16_LE);
}
static int configure(int32_t encoded,char **map) {
    if(map)*map=NULL;
    return encoded==get_configuration(0,0,0)?0:-1;
}
static int play(void *buf,int samples,int type,uint32_t timestamp,uint64_t playtime) {
    (void)timestamp;
    /* Worker supplies continuous silence itself. Untimed lead-in must not shift
     * the source timeline or fill the queue before real media arrives. */
    if(type!=play_samples_are_timed || samples<=0)return 0;
    uint64_t absolute=get_absolute_time_in_ns(),mono=mono_ns();
    uint64_t distance=playtime>=absolute?playtime-absolute:absolute-playtime;
    if(distance>5000000000ULL) {
        warn("AirConnect rejected a presentation timestamp outside the five-second bound.");
        pthread_mutex_lock(&lock);failed=1;pthread_mutex_unlock(&lock);return -1;
    }
    int64_t delta=playtime>=absolute?(int64_t)distance:-(int64_t)distance;
    uint64_t when=(uint64_t)((int64_t)mono+delta);
    int cancellation;pthread_setcancelstate(PTHREAD_CANCEL_DISABLE,&cancellation);
    pthread_mutex_lock(&lock);int result=-1;
    if(failed || fd<0)goto done;
    const uint8_t *pcm=buf;size_t sent=0;
    while(sent<(size_t)samples) {
        uint32_t count=(uint32_t)((size_t)samples-sent);if(count>AP2_MAX_FRAMES)count=AP2_MAX_FRAMES;
        uint8_t h[24]={0};ap2_put32(h,AP2_MAGIC);ap2_put32(h+4,AP2_AUDIO);ap2_put32(h+8,count);
        ap2_put64(h+16,when+(uint64_t)sent*1000000000/AP2_RATE);
        if(send_all(h,sizeof(h)) || send_all(pcm+sent*4,count*4))goto done;
        sent+=count;
    }
    result=0;
 done:
    pthread_mutex_unlock(&lock);pthread_setcancelstate(cancellation,NULL);return result;
}
static void flush(void) {
    int cancellation;pthread_setcancelstate(PTHREAD_CANCEL_DISABLE,&cancellation);
    pthread_mutex_lock(&lock);
    if(fd>=0 && !failed){uint8_t h[24]={0};ap2_put32(h,AP2_MAGIC);ap2_put32(h+4,AP2_FLUSH);send_all(h,sizeof(h));}
    pthread_mutex_unlock(&lock);pthread_setcancelstate(cancellation,NULL);
}
static void stop(void){int cancellation;pthread_setcancelstate(PTHREAD_CANCEL_DISABLE,&cancellation);pthread_mutex_lock(&lock);finish_locked();pthread_mutex_unlock(&lock);pthread_setcancelstate(cancellation,NULL);}
static int is_running(void) {
    pthread_mutex_lock(&lock);
    if(child>0){int status;pid_t r=waitpid(child,&status,WNOHANG);
        /* Shairport's SIGCHLD handler may already have reaped this child. */
        if(r==child || (r<0 && errno==ECHILD)){child=-1;failed=1;}}
    int result=failed;pthread_mutex_unlock(&lock);
    if(result)die("AirConnect output failed; stopping receiver. See worker diagnostics.");
    return result;
}
audio_output audio_airconnect={.name="airconnect",.init=init,.deinit=stop,.prepare=prepare,
    .get_configuration=get_configuration,.configure=configure,.play=play,.stop=stop,
    .is_running=is_running,.flush=flush,.delay=NULL,.stats=NULL,.volume=NULL,.parameters=NULL,.mute=NULL};
