/* Explicit test driver: always muted. No mDNS advertisement or service change. */
#include "sonos_native.h"
#include "cross_log.h"
#include <stdlib.h>
#include <stdio.h>
log_level main_loglevel=lINFO;
int main(int argc,char **argv) {
    if(argc!=7) {fprintf(stderr,"helper.json local-ip receiver-url receiver-udn seconds volume\n");return 2;}
    int seconds=atoi(argv[5]);if(seconds<1||seconds>180)return 2;
    snprintf(glNativeHelperConfig,sizeof(glNativeHelperConfig),"%s",argv[1]);
    if(sonos_native_load_helper())return 3;
    struct sonos_native_device *d=sonos_native_device_new(argv[2],argv[3],argv[4],1);
    if(!d)return 4;
    sonos_native_volume(d,atoi(argv[6]));raop_pcm_output_t out=sonos_native_output(d);
    volatile bool running=true;
    void *s=out.open(out.owner,&running);if(!s){sonos_native_device_free(d);return 5;}
    uint8_t pcm[1004]={0};int rc=0;
    for(int i=0;i<seconds*44100/251;++i) {if(out.write(s,pcm,sizeof(pcm))){rc=6;break;}}
    out.close(s);sonos_native_device_free(d);return rc;
}
