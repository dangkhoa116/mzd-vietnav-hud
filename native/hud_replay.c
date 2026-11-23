/* SPDX-License-Identifier: AGPL-3.0-or-later */
/* Offline HUD emulator: actual ATT/frame/guidance/arrow/VBS code, a fake OEM
 * service bus. No radio/UART/vehicle writes, even on ARM under qemu-user. */
#include "hud_native.h"
#include "hud_arrow.h"
#include "vn_vbs.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static struct vn_hud hud;
static struct vn_vbs_display display;
static unsigned char model[VN_ARROW_MODEL_MAX];
static unsigned model_size, messages;

static void json_string(const char *s)
{
    const unsigned char *p=(const unsigned char *)s;
    putchar('"');
    while (*p) {
        if (*p=='"' || *p=='\\') { putchar('\\');putchar(*p); }
        else if (*p<32) printf("\\u%04x",*p);
        else putchar(*p);
        p++;
    }
    putchar('"');
}
static void *create(void *cb,int reserved) { (void)cb;(void)reserved;return &hud; }
static int connect_bus(void *c,const char *name,int bus,void *reserved)
{ (void)c;(void)name;(void)bus;(void)reserved;return 1; }
static int start_worker(void *c) { (void)c;return 1; }
static void nothing(void *c) { (void)c; }
static int status(void *c,void *cb,void *u) { (void)c;(void)cb;(void)u;return 0; }
static int msg1(void *c,void *p,void *a,void *b,void *d)
{ (void)c;(void)a;(void)b;(void)d;display=*(struct vn_vbs_display *)p;return 0; }
static int msg2(void *c,void *p,void *a,void *b,void *d)
{
    const struct vn_vbs_msg2 *street=(const struct vn_vbs_msg2 *)p;
    (void)c;(void)a;(void)b;(void)d;
    printf("{\"type\":\"hud\",\"icon\":%u,\"distanceValue\":%u,\"distanceUnit\":%u,"
           "\"speedLimit\":%u,\"speedUnit\":%u,\"sync\":%u,\"streetSync\":%u,\"road\":",
           display.next_maneuver_info,display.distance_value,display.distance_unit,
           display.display_speed_limit,display.display_speed_unit,display.text_id3,street->sync_bit);
    json_string(street->guidance_point_name);puts("}");messages++;return 0;
}
static int send_hci(void *u,const unsigned char *p,unsigned n)
{ (void)u;(void)p;(void)n;return 1; }
static void guide(void *u,const struct vn_guidance *g) { (void)u;vn_vbs_guide(g); }
static unsigned arrow(void *u,const unsigned char *p,unsigned n)
{ struct vn_arrow_result r;(void)u;return vn_arrow_match(model,model_size,p,n,&r)?r.icon:0; }
static unsigned be32(const unsigned char *p)
{ return ((unsigned)p[0]<<24)|((unsigned)p[1]<<16)|((unsigned)p[2]<<8)|p[3]; }
int main(int argc,char **argv)
{
    FILE *input;
    unsigned char frame[VN_FRAME_MAX],att[23];
    unsigned n,i,chunk,op;
    uint64_t now=1000;
    struct vn_caps caps;
    struct vn_io io={0,send_hci,0,guide};
    struct vn_vbs_calls calls={create,connect_bus,start_worker,nothing,nothing,nothing,msg1,msg2,status};
    if (argc!=3) { fprintf(stderr,"usage: hud-replay arrows.vna frames.bin\n");return 2; }
    input=fopen(argv[1],"rb");
    if (!input) return 2;
    model_size=(unsigned)fread(model,1,sizeof model,input);
    if (fgetc(input)!=EOF || !vn_arrow_model_valid(model,model_size)) { fclose(input);return 3; }
    fclose(input);
    input=fopen(argv[2],"rb");if (!input) return 2;
    memset(&caps,0,sizeof caps);
    caps.commands_seen=caps.states_seen=caps.buffer_seen=1;
    caps.commands[25]=0xa0;caps.commands[26]=3;caps.states[0]=0x84;
    caps.acl_size=27;caps.acl_count=15;
    vn_vbs_bind(&calls);vn_init(&hud,io);vn_set_arrow_matcher(&hud,arrow,0);
    if (!vn_start(&hud,&caps,1,now,180000)) return 4;
    for (i=0;i<4;i++) {
        now+=200;vn_tick(&hud,now,1);op=hud.pending;
        vn_command_reply(&hud,op,0,now);
    }
    vn_connected(&hud,0,0x41,1,now);
    puts("{\"type\":\"replay\",\"radio\":false,\"oemBus\":\"fake\"}");
    for (;;) {
        n=(unsigned)fread(frame,1,8,input);
        if (!n && feof(input)) break;
        if (n!=8 || memcmp(frame,"\xa5\x5a\x37\xc3",4) ||
            be32(frame+4)<13 || be32(frame+4)>VN_FRAME_MAX-8) { fclose(input);return 5; }
        n=be32(frame+4)+8;
        if (fread(frame+8,1,n-8,input)!=n-8) { fclose(input);return 5; }
        for (i=0;i<n;i+=chunk) {
            chunk=n-i>20?20:n-i;
            att[0]=0x52;att[1]=14;att[2]=0;
            memcpy(att+3,frame+i,chunk);vn_att(&hud,att,chunk+3);
        }
        now+=100;vn_tick(&hud,now,1);
    }
    fclose(input);
    /* A silent but connected app must not leave guidance frozen indefinitely. */
    vn_tick(&hud,now+VN_GUIDANCE_STALE_MS+1,1);
    vn_vbs_stop();
    fprintf(stderr,"replay: %u paired HUD messages; no radio or vehicle I/O\n",messages);
    return 0;
}
