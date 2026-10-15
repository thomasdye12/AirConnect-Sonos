#define _DARWIN_C_SOURCE 1
#include "sonos_native.h"
#include "sonos_sender.h"
#include "ixmlextra.h"
#include "upnp.h"
#include "upnptools.h"
#include "jansson.h"
#include "cross_log.h"
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

extern log_level main_loglevel;
static log_level *loglevel = &main_loglevel;
char glNativeHelperConfig[512] = "/var/airplay_sonos/native-helper.json";
static char helper_ip[16], helper_id[32];
#define AV "AVTransport"
#define RC "RenderingControl"
#define TZ "ZoneGroupTopology"
#define LIMIT (1024 * 1024)
struct pair { const char *key, *value; };
struct state { char *uri, *meta; char group[160]; int volume, mute; };
struct sonos_native_device {
    char local[16], ip[16], id[32];
    pthread_mutex_t mutex;
    int volume, muted, active;
};
struct session {
    struct sonos_native_device *device;
    struct sonos_sender *sender;
    struct state receiver, helper;
    char settings[256];
    int receiver_lock, helper_lock, changed, helper_released;
    uint64_t pcm_frames, signal_frames;
    pthread_t control;
    pthread_mutex_t mutex;
    int control_started, stop, failed;
};
static uint64_t millis(void) {
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}
static void delay_ms(unsigned ms) {
    struct timespec ts = {ms / 1000, (ms % 1000) * 1000000};
    while (nanosleep(&ts, &ts) && errno == EINTR) {}
}
static int identity(const char *s) {
    if (!s || strlen(s) != 24 || strncmp(s, "RINCON_", 7)) return 0;
    return strspn(s + 7, "0123456789ABCDEF") == 17;
}
int sonos_native_load_helper(void) {
    helper_ip[0] = helper_id[0] = 0;
    struct stat st;
    if (stat(glNativeHelperConfig, &st) || st.st_size > LIMIT) return -1;
    json_error_t error;
    json_t *root = json_load_file(glNativeHelperConfig, 0, &error);
    json_t *h = root ? json_object_get(root, "helper") : NULL;
    const char *ip = json_string_value(json_object_get(h, "address"));
    const char *id = json_string_value(json_object_get(h, "uuid"));
    struct in_addr addr;
    int ok = json_integer_value(json_object_get(root, "version")) == 1 &&
        ip && inet_pton(AF_INET, ip, &addr) == 1 && identity(id);
    if (ok) { snprintf(helper_ip, sizeof(helper_ip), "%s", ip); snprintf(helper_id, sizeof(helper_id), "%s", id); }
    if (root) json_decref(root);
    return ok ? 0 : -1;
}
int sonos_native_is_helper(const char *udn) {
    return *helper_id && udn && !strncmp(udn, "uuid:", 5) && !strcmp(udn + 5, helper_id);
}
/* Same file names and directory as research/device_lease.py; never unlink. */
static int lease(const char *id, const volatile bool *running) {
    char dir[768], path[1024], encoded[128];
    const char *tmp = getenv("TMPDIR");
    if (!tmp || !*tmp) tmp = "/tmp";
    snprintf(dir, sizeof(dir), "%s/airconnect-native-%u", tmp, (unsigned)getuid());
    if (mkdir(dir, 0700) && errno != EEXIST) return -1;
    struct stat st;
    if (lstat(dir, &st) || !S_ISDIR(st.st_mode) || st.st_uid != getuid() || (st.st_mode & 077)) return -1;
    for (size_t i = 0; i <= strlen(id); ++i) snprintf(encoded + i * 2, 3, "%02x", (unsigned char)id[i]);
    encoded[strlen(id)*2] = 0;
    snprintf(path, sizeof(path), "%s/%s.lock", dir, encoded);
    int fd = open(path, O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) return -1;
    uint64_t deadline = millis() + 15000;
    while (flock(fd, LOCK_EX | LOCK_NB)) {
        if (!*running || (errno != EWOULDBLOCK && errno != EAGAIN) || millis() >= deadline) { close(fd); return -1; }
        delay_ms(50);
    }
    return fd;
}
static void release(int *fd) { if (*fd >= 0) { flock(*fd, LOCK_UN); close(*fd); *fd = -1; } }

/* Bounded numeric-IPv4 HTTP. Every SOAP response must be HTTP 200 and XML.
 * No shell, account credentials, TLS identity impersonation or firmware changes. */
static IXML_Document *soap(const char *ip, const char *service, const char *name, const struct pair *args) {
    char type[128], path[128];
    snprintf(type, sizeof(type), "urn:schemas-upnp-org:service:%s:1", service);
    snprintf(path, sizeof(path), "%s/%s/Control", !strcmp(service,TZ) || !strcmp(service,"GroupManagement") ? "" : "/MediaRenderer", service);
    IXML_Document *action = NULL, *result = NULL;
    if (args) for (const struct pair *p = args; p->key; ++p)
        if (UpnpAddToAction(&action, name, type, p->key, p->value) != UPNP_E_SUCCESS) goto done;
    if (!action) action = UpnpMakeAction(name, type, 0, NULL);
    if (!action) goto done;
    char *xml = ixmlDocumenttoString(action), *body = NULL, *request = NULL, *response = NULL;
    int fd = -1;
    if (!xml) goto done;
    char *fragment = !strncmp(xml, "<?xml", 5) ? strstr(xml, "?>") : NULL;
    fragment = fragment ? fragment + 2 : xml;
    if (asprintf(&body, "<s:Envelope xmlns:s=\"http://schemas.xmlsoap.org/soap/envelope/\" s:encodingStyle=\"http://schemas.xmlsoap.org/soap/encoding/\"><s:Body>%s</s:Body></s:Envelope>", fragment) < 0) { free(xml); goto done; }
    free(xml);
    if (asprintf(&request, "POST %s HTTP/1.1\r\nHost: %s:1400\r\nConnection: close\r\nContent-Type: text/xml; charset=\"utf-8\"\r\nSOAPACTION: \"%s#%s\"\r\n%sContent-Length: %zu\r\n\r\n%s", path, ip, type, name, !strcmp(name,"BecomeGroupCoordinator") ? "x-sonos-clone-gc: 1\r\n" : "", strlen(body), body) < 0) goto cleanup;
    fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) goto cleanup;
    int flags = fcntl(fd, F_GETFL, 0); fcntl(fd, F_SETFL, flags | O_NONBLOCK);
    struct sockaddr_in addr = {0}; addr.sin_family = AF_INET; addr.sin_port = htons(1400);
    if (inet_pton(AF_INET, ip, &addr.sin_addr) != 1) goto cleanup;
    int rc = connect(fd, (struct sockaddr*)&addr, sizeof(addr));
    if (rc && errno != EINPROGRESS) goto cleanup;
    struct pollfd pfd = {fd, POLLOUT, 0};
    if (poll(&pfd, 1, 2000) <= 0) goto cleanup;
    int err = 0; socklen_t len = sizeof(err);
    if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &err, &len) || err) goto cleanup;
    fcntl(fd, F_SETFL, flags);
    struct timeval timeout = {2,0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
#ifdef SO_NOSIGPIPE
    int one = 1; setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof(one));
#endif
    size_t sent = 0, length = strlen(request); uint64_t deadline = millis() + 5000;
    while (sent < length && millis() < deadline) {
        ssize_t n = send(fd, request + sent, length - sent,
#ifdef MSG_NOSIGNAL
            MSG_NOSIGNAL
#else
            0
#endif
        );
        if (n <= 0) goto cleanup;
        sent += n;
    }
    if (sent != length) goto cleanup;
    response = malloc(LIMIT + 1); if (!response) goto cleanup;
    size_t used = 0;
    while (used < LIMIT && millis() < deadline) {
        ssize_t n = recv(fd, response + used, LIMIT - used, 0);
        if (n < 0) goto cleanup;
        if (!n) break;
        used += n; response[used] = 0;
        char *end = strstr(response, "\r\n\r\n");
        char *cl = strcasestr(response, "\r\nContent-Length:");
        if (end && cl && cl < end && used >= (size_t)(end + 4 - response) + strtoul(cl + 17, NULL, 10)) break;
    }
    response[used] = 0;
    char *end = strstr(response, "\r\n\r\n"); int status = 0;
    sscanf(response, "HTTP/%*s %d", &status);
    if (status == 200 && end) result = ixmlParseBuffer(end + 4);
    if (!result) LOG_ERROR("native SOAP %s HTTP=%d response=%.700s", name, status, end ? end + 4 : response);
cleanup:
    if (fd >= 0) close(fd);
    free(body); free(request); free(response);
done:
    if (!result) LOG_ERROR("native %s failed on %s", name, ip);
    if (action) ixmlDocument_free(action);
    return result;
}
static int action(const char *ip,const char *service,const char *name,const struct pair *args) {
    IXML_Document *doc = soap(ip,service,name,args);
    if (!doc) return -1;
    ixmlDocument_free(doc); return 0;
}
static char *value(const char *ip,const char *service,const char *name,const char *key) {
    const struct pair args[] = {{"InstanceID","0"},{!strcmp(service,RC) ? "Channel" : NULL,"Master"},{NULL,NULL}};
    IXML_Document *doc = soap(ip,service,name,args);
    if (!doc) return NULL;
    char *v = XMLGetFirstDocumentItem(doc,(char*)key,true);
    if (!v) {
        IXML_NodeList *nodes = ixmlDocument_getElementsByTagName(doc, key);
        if (ixmlNodeList_length(nodes)) v = strdup("");
        ixmlNodeList_free(nodes);
    }
    ixmlDocument_free(doc); return v;
}
static int basic(const char *ip,const char *name) {
    const struct pair args[] = {{"InstanceID","0"},{NULL,NULL}};
    return action(ip,AV,name,args);
}
static int render(const char *ip,const char *name,int number) {
    char val[16]; snprintf(val,sizeof(val),"%d",number);
    const struct pair args[] = {{"InstanceID","0"},{"Channel","Master"},{!strcmp(name,"SetMute") ? "DesiredMute" : "DesiredVolume",val},{NULL,NULL}};
    return action(ip,RC,name,args);
}
static int seturi(const char *ip,const char *uri,const char *meta) {
    const struct pair args[]={{"InstanceID","0"},{"CurrentURI",uri},{"CurrentURIMetaData",meta},{NULL,NULL}};
    return action(ip,AV,"SetAVTransportURI",args);
}
static IXML_Document *topology(const char *ip) {
    IXML_Document *doc=soap(ip,TZ,"GetZoneGroupState",NULL); if (!doc) return NULL;
    char *raw=XMLGetFirstDocumentItem(doc,"ZoneGroupState",true);
    IXML_Document *result=raw ? ixmlParseBuffer(raw) : NULL;
    free(raw); ixmlDocument_free(doc); return result;
}
static int standalone(IXML_Document *doc,const char *id,const char *ip,char *group) {
    if (!doc) return 0;
    int ok=0; IXML_NodeList *groups=ixmlDocument_getElementsByTagName(doc,"ZoneGroup");
    for (unsigned i=0;i<ixmlNodeList_length(groups);++i) {
        IXML_Element *g=(IXML_Element*)ixmlNodeList_item(groups,i);
        const char *coord=ixmlElement_getAttribute(g,"Coordinator");
        if (!coord || strcmp(coord,id)) continue;
        IXML_NodeList *members=ixmlElement_getElementsByTagName(g,"ZoneGroupMember");
        if (ixmlNodeList_length(members)==1) {
            IXML_Element *m=(IXML_Element*)ixmlNodeList_item(members,0);
            const char *uid=ixmlElement_getAttribute(m,"UUID"), *loc=ixmlElement_getAttribute(m,"Location");
            char prefix[64];snprintf(prefix,sizeof(prefix),"http://%s:1400/",ip);
            ok=uid && !strcmp(uid,id) && loc && !strncmp(loc,prefix,strlen(prefix));
            const char *gid=ixmlElement_getAttribute(g,"ID");
            if (ok && group) { if (!gid || strlen(gid)>=160) ok=0; else strcpy(group,gid); }
        }
        ixmlNodeList_free(members);
    }
    ixmlNodeList_free(groups); return ok;
}
static void state_free(struct state *s) { free(s->uri);free(s->meta);memset(s,0,sizeof(*s)); }
static int snapshot(const char *ip,const char *id,struct state *s) {
    char *transport=value(ip,AV,"GetTransportInfo","CurrentTransportState");
    int ok=transport && !strcmp(transport,"STOPPED"); free(transport);
    if (!ok) return -1;
    IXML_Document *top=topology(ip); ok=ok && standalone(top,id,ip,s->group); if(top)ixmlDocument_free(top);
    if (!ok) return -1;
    s->uri=value(ip,AV,"GetMediaInfo","CurrentURI"); s->meta=value(ip,AV,"GetMediaInfo","CurrentURIMetaData");
    char *mute=value(ip,RC,"GetMute","CurrentMute"), *vol=value(ip,RC,"GetVolume","CurrentVolume");
    ok=s->uri && s->meta && mute && vol;
    if (ok) {s->mute=atoi(mute);s->volume=atoi(vol);ok=s->mute>=0&&s->mute<=1&&s->volume>=0&&s->volume<=100;}
    free(mute);free(vol);return ok ? 0 : -1;
}
static int restore(const char *ip,const char *id,const struct state *s,int detach) {
    int rc=render(ip,"SetMute",1);
    if(detach) rc|=basic(ip,"BecomeCoordinatorOfStandaloneGroup");
    rc|=seturi(ip,s->uri,s->meta);rc|=basic(ip,"Stop");
    rc|=render(ip,"SetVolume",s->volume);rc|=render(ip,"SetMute",s->mute);
    struct state after={0};int verified=snapshot(ip,id,&after)==0 && !strcmp(after.uri,s->uri) && !strcmp(after.meta,s->meta) && after.volume==s->volume && after.mute==s->mute;
    state_free(&after);
    LOG_INFO("native restore %s: %s",ip,!rc&&verified?"verified":"FAILED");
    return !rc&&verified ? 0 : -1;
}
static int separated(struct session *s) {
    int ok=1;const char *ips[]={s->device->ip,helper_ip};
    for(int i=0;i<2;++i) {
        IXML_Document *top=topology(ips[i]);
        ok=ok && standalone(top,s->device->id,s->device->ip,NULL) && standalone(top,helper_id,helper_ip,NULL);
        if(top)ixmlDocument_free(top);
    }
    return ok;
}
static int stopped(struct session *s) {pthread_mutex_lock(&s->mutex);int stop=s->stop;pthread_mutex_unlock(&s->mutex);return stop;}
static void *control(void *arg) {
    struct session *s=arg;struct sonos_native_device *d=s->device;
    uint64_t first=0;int promoted=0,last_volume=-1;
    while(!stopped(s)) {
        pthread_mutex_lock(&d->mutex);int volume=d->volume;pthread_mutex_unlock(&d->mutex);
        if(volume<0)volume=s->receiver.volume;
        if(volume!=last_volume) {
            if(render(d->ip,"SetVolume",volume) || render(d->ip,"SetMute",d->muted || volume==0)) goto fail;
            last_volume=volume;
        }
        struct sonos_sender_stats stats;sonos_sender_get_stats(s->sender,&stats);
        if(!first && stats.packets)first=millis();
        if(!promoted && first && millis()-first>=3000) {
            char transport[256],uri[80];strcpy(transport,s->settings);char *comma=strrchr(transport,',');if(comma)comma[1]=0;
            snprintf(uri,sizeof(uri),"x-rincon-stream:RINCON_02%.10s01400:0",d->id+9);
            const struct pair args[]={{"InstanceID","0"},{"CurrentCoordinator",helper_id},{"CurrentGroupID",s->receiver.group},{"OtherMembers",""},{"TransportSettings",transport},{"CurrentURI",uri},{"CurrentURIMetaData",""},{"SleepTimerState",""},{"AlarmState",""},{"StreamRestartState",""},{"SharedQueueTrackList",""},{"PrivateQueueTrackList",""},{"CurrentVLIState",""},{NULL,NULL}};
            if(action(d->ip,AV,"BecomeGroupCoordinator",args))goto fail;
            uint64_t deadline=millis()+3000;int clean;
            do {clean=separated(s);if(clean)break;delay_ms(150);}while(!stopped(s)&&millis()<deadline);
            if(stopped(s))return NULL;
            if(!clean) {
                const struct pair remove[]={{"MemberID",d->id},{NULL,NULL}};
                if(action(helper_ip,"GroupManagement","RemoveMember",remove) || basic(helper_ip,"BecomeCoordinatorOfStandaloneGroup") || !separated(s))goto fail;
            }
            if(restore(helper_ip,helper_id,&s->helper,0))goto fail;
            release(&s->helper_lock);
            pthread_mutex_lock(&s->mutex);s->helper_released=1;pthread_mutex_unlock(&s->mutex);promoted=1;
            LOG_INFO("native helper released; independent PCM continues for %s",d->ip);
        }
        delay_ms(100);
    }
    return NULL;
fail:
    pthread_mutex_lock(&s->mutex);s->failed=1;pthread_mutex_unlock(&s->mutex);
    LOG_ERROR("native control failed for %s; closing and restoring",d->ip);
    return NULL;
}
static void session_close(void *ctx) {
    struct session *s=ctx;
    pthread_mutex_lock(&s->mutex);s->stop=1;pthread_mutex_unlock(&s->mutex);
    if(s->control_started)pthread_join(s->control,NULL);
    if(s->sender) {
        struct sonos_sender_stats stats;sonos_sender_get_stats(s->sender,&stats);
        LOG_INFO("native sender %s packets=%llu clocks=%llu late=%llu pcm_frames=%llu signal_frames=%llu",s->device->ip,(unsigned long long)stats.packets,(unsigned long long)stats.clock_requests,(unsigned long long)stats.late_packets,(unsigned long long)s->pcm_frames,(unsigned long long)s->signal_frames);
        sonos_sender_close(s->sender);
    }
    if(s->changed) {
        restore(s->device->ip,s->device->id,&s->receiver,1);
        if(!s->helper_released)restore(helper_ip,helper_id,&s->helper,1);
    }
    release(&s->helper_lock);release(&s->receiver_lock);
    state_free(&s->receiver);state_free(&s->helper);
    pthread_mutex_lock(&s->device->mutex);s->device->active=0;pthread_mutex_unlock(&s->device->mutex);
    pthread_mutex_destroy(&s->mutex);free(s);
}
static void *session_open(void *owner, const volatile bool *running) {
    struct sonos_native_device *d=owner;
    pthread_mutex_lock(&d->mutex);int active=d->active;d->active=1;pthread_mutex_unlock(&d->mutex);
    if(active)return NULL;
    struct session *s=calloc(1,sizeof(*s));
    if(!s){pthread_mutex_lock(&d->mutex);d->active=0;pthread_mutex_unlock(&d->mutex);return NULL;}
    s->device=d;s->receiver_lock=s->helper_lock=-1;pthread_mutex_init(&s->mutex,NULL);
    s->receiver_lock=lease(d->id,running);if(s->receiver_lock<0)goto fail;
    s->helper_lock=lease(helper_id,running);if(s->helper_lock<0)goto fail;
    if(!*running || snapshot(d->ip,d->id,&s->receiver)||snapshot(helper_ip,helper_id,&s->helper)) {
        LOG_ERROR("native setup refused: receiver/helper must match identity and be stopped standalone");goto fail;
    }
    s->sender=sonos_sender_open(d->local,d->ip,7020,0,75000);if(!s->sender)goto fail;
    if(!*running)goto fail;
    s->changed=1;
    if(render(d->ip,"SetMute",1)||render(helper_ip,"SetMute",1))goto fail;
    char uri[80];snprintf(uri,sizeof(uri),"x-rincon:%s",helper_id);
    if(seturi(d->ip,uri,""))goto fail;
    snprintf(s->settings,sizeof(s->settings),"234.142.199.198:7020,%s:7000:7010:%u,%s",d->local,sonos_sender_clock_port(s->sender),helper_id);
    const struct pair args[]={{"InstanceID","0"},{"NewTransportSettings",s->settings},{"CurrentAVTransportURI",uri},{NULL,NULL}};
    if(action(d->ip,AV,"ChangeTransportSettings",args))goto fail;
    if(pthread_create(&s->control,NULL,control,s))goto fail;
    s->control_started=1;LOG_INFO("native PCM started for %s",d->ip);return s;
fail:
    session_close(s);return NULL;
}
static int session_write(void *ctx,const uint8_t *pcm,size_t bytes) {
    struct session *s=ctx;
    pthread_mutex_lock(&s->mutex);int failed=s->failed;pthread_mutex_unlock(&s->mutex);
    if(failed)return -1;
    for(size_t i=0;i+3<bytes;i+=4) { s->pcm_frames++; if(pcm[i]||pcm[i+1]||pcm[i+2]||pcm[i+3])s->signal_frames++; }
    return sonos_sender_write(s->sender,pcm,bytes);
}
struct sonos_native_device *sonos_native_device_new(const char *local,const char *location,const char *udn,int muted) {
    if(!*helper_id || !udn || strncmp(udn,"uuid:",5) || !identity(udn+5) || sonos_native_is_helper(udn))return NULL;
    struct sonos_native_device *d=calloc(1,sizeof(*d));if(!d)return NULL;
    struct in_addr addr;
    if(sscanf(location,"http://%15[^:]:",d->ip)!=1 || inet_pton(AF_INET,d->ip,&addr)!=1 || inet_pton(AF_INET,local,&addr)!=1){free(d);return NULL;}
    strcpy(d->local,local);strcpy(d->id,udn+5);d->volume=-1;d->muted=muted;
    pthread_mutex_init(&d->mutex,NULL);return d;
}
void sonos_native_device_free(struct sonos_native_device *d) {if(d){pthread_mutex_destroy(&d->mutex);free(d);}}
raop_pcm_output_t sonos_native_output(struct sonos_native_device *d) {
    raop_pcm_output_t out={0};if(d){out.owner=d;out.open=session_open;out.write=session_write;out.close=session_close;out.lead_ms=75;}return out;
}
void sonos_native_volume(struct sonos_native_device *d,int volume) {
    if(!d)return;
    pthread_mutex_lock(&d->mutex);d->volume=volume<0?0:volume>100?100:volume;pthread_mutex_unlock(&d->mutex);
}
int sonos_native_session_ready(void *ctx) {
    struct session *s=ctx;
    pthread_mutex_lock(&s->mutex);int ready=s->helper_released && !s->failed;pthread_mutex_unlock(&s->mutex);
    return ready;
}
