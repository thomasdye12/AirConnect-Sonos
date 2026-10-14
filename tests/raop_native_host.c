/* Bounded real RAOP receiver wired to the production PCM callbacks; always muted. */
#include "../common/libraop/src/raop_server.c"
#include "sonos_native.h"
log_level main_loglevel=lINFO, raop_loglevel=lINFO, util_loglevel=lWARN;
static void event(void *owner,raopsr_event_t type,...) {(void)owner;(void)type;}
int main(int argc,char **argv) {
    if(argc!=6)return 2;
    struct in_addr host;if(inet_pton(AF_INET,argv[2],&host)!=1)return 2;
    int seconds=atoi(argv[5]);if(seconds<1||seconds>180)return 2;
    snprintf(glNativeHelperConfig,sizeof(glNativeHelperConfig),"%s",argv[1]);
    if(sonos_native_load_helper())return 3;
    struct sonos_native_device *d=sonos_native_device_new(argv[2],argv[3],argv[4],1);if(!d)return 4;
    raop_pcm_output_t pcm=sonos_native_output(d);
    struct mdnsd *mdns=mdnsd_start(host,false);if(!mdns)return 5;
    mdnsd_set_hostname(mdns,"native-validation.local",host);
    uint8_t mac[]={2,0,0,0,0,0x78};
    struct raopsr_s *r=raopsr_create_pcm(host,mdns,"Native validation (test)","airupnp",mac,"flac",false,false,true,"500:0",NULL,event,NULL,0,1,0,&pcm);
    if(!r)return 6;
    printf("READY %u\n",r->port);fflush(stdout);
    sleep(seconds);
    raopsr_delete(r);mdnsd_stop(mdns);sonos_native_device_free(d);return 0;
}
