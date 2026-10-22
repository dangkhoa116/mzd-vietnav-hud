/* SPDX-License-Identifier: AGPL-3.0-or-later */
/* Host harness for hud_guidance.c (decode/feed/normalize) and the vn_vbs.c
 * sender with a capturing fake backend. No D-Bus, no dl; bound via
 * vn_vbs_bind() from the test process.
 */
#include "hud_guidance.h"
#include "vn_vbs.h"
#include <string.h>

static struct vn_nav nav;
static struct vn_guide_state feed_state;

static void copy_str(char *dst, unsigned sz, const char *src)
{
    unsigned i;
    for (i = 0; i + 1 < sz && src && src[i]; i++)
        dst[i] = src[i];
    dst[i] = 0;
}

int gd_decode(const unsigned char *buf, unsigned n)
{
    memset(&nav, 0, sizeof nav);
    return vn_nav_decode(&nav, buf, n);
}
unsigned gd_distance(void) { return nav.distance_m; }
unsigned gd_remain_time(void) { return nav.remain_time_s; }
unsigned gd_remain_dist(void) { return nav.remain_dist_m; }
unsigned gd_speed(void) { return nav.speed_kmh; }
unsigned gd_limit(void) { return nav.speed_limit; }
unsigned gd_direction(void) { return nav.direction; }
unsigned gd_layout(void) { return nav.layout; }
void gd_road(int which, char *dst, unsigned sz)
{
    copy_str(dst, sz, which ? nav.current_road : nav.next_road);
}

void gd_feed_reset(void) { memset(&feed_state, 0, sizeof feed_state); }

int gd_feed(unsigned distance, const char *next_road, const char *current_road,
            unsigned limit, unsigned icon_hint, struct vn_guidance *out)
{
    struct vn_nav input;
    memset(&input, 0, sizeof input);
    input.distance_m = distance;
    input.speed_limit = limit;
    copy_str(input.next_road, sizeof input.next_road, next_road);
    copy_str(input.current_road, sizeof input.current_road, current_road);
    memset(out, 0, sizeof *out);
    return vn_guide_feed(&feed_state, out, &input, icon_hint);
}

unsigned gd_normalize(const char *src, char *dst, unsigned sz)
{
    return vn_normalize_vn(src, dst, sz);
}

/* === capturing fake OEM backend ================================== */

static struct {
    int created, connected, started, worker_stopped, disconnected, freed;
    int fail_create, fail_connect, fail_msg, fail_msg2;
    unsigned char status_reply;
    char name[64];
    int jcibus;
    int msg_calls, msg2_calls;
    struct vn_vbs_display disp;
    char road[300];
    unsigned msg2_sync;
    char logs[8][128];
    int log_count;
} f;

static void *f_conn_create(void *cb, int reserved)
{
    (void)cb;
    (void)reserved;
    f.created++;
    return f.fail_create ? 0 : (void *)&f;
}
static int f_conn_connect(void *conn, const char *name, int jcibus, void *reserved)
{
    (void)conn;
    (void)reserved;
    f.connected++;
    copy_str(f.name, sizeof f.name, name);
    f.jcibus = jcibus;
    return f.fail_connect ? 0 : 1;
}
static int f_worker_start(void *conn)
{
    (void)conn;
    f.started++;
    return 1;
}
static void f_worker_stop(void *conn) { (void)conn; f.worker_stopped++; }
static void f_conn_disconnect(void *conn) { (void)conn; f.disconnected++; }
static void f_conn_free(void *conn) { (void)conn; f.freed++; }
static int f_set_msg(void *conn, void *disp, void *unused, void *cb, void *user)
{
    (void)conn;
    (void)unused;
    (void)cb;
    (void)user;
    if (f.fail_msg)
        return -1;
    f.disp = *(struct vn_vbs_display *)disp;
    f.msg_calls++;
    return 0;
}
static int f_set_msg2(void *conn, void *msg2, void *unused, void *cb, void *user)
{
    const struct vn_vbs_msg2 *m = msg2;
    (void)conn;
    (void)unused;
    (void)cb;
    (void)user;
    if (f.fail_msg2)
        return -1;
    copy_str(f.road, sizeof f.road, m->guidance_point_name);
    f.msg2_sync = m->sync_bit;
    f.msg2_calls++;
    return 0;
}
static int f_get_status(void *conn, void *cb, void *user)
{
    ((void (*)(void *, unsigned char, void *))cb)(conn, f.status_reply, user);
    return 0;
}
static void f_log(const char *msg)
{
    if (f.log_count < 8)
        copy_str(f.logs[f.log_count++], 128, msg);
}

void gd_vbs_reset(void)
{
    struct vn_vbs_calls calls;
    memset(&calls, 0, sizeof calls);
    memset(&f, 0, sizeof f);
    f.status_reply = 1; /* HUD present unless a test says otherwise */
    calls.conn_create = f_conn_create;
    calls.conn_connect = f_conn_connect;
    calls.worker_start = f_worker_start;
    calls.worker_stop = f_worker_stop;
    calls.conn_disconnect = f_conn_disconnect;
    calls.conn_free = f_conn_free;
    calls.set_hud_msg = f_set_msg;
    calls.set_hud_msg2 = f_set_msg2;
    calls.get_hud_status = f_get_status;
    vn_vbs_bind(&calls);
    vn_vbs_set_logger(f_log);
}

int gd_vbs_created(void) { return f.created; }
int gd_vbs_connected(void) { return f.connected; }
int gd_vbs_started(void) { return f.started; }
int gd_vbs_worker_stopped(void) { return f.worker_stopped; }
int gd_vbs_disconnected(void) { return f.disconnected; }
int gd_vbs_freed(void) { return f.freed; }
void gd_vbs_name(char *dst, unsigned sz) { copy_str(dst, sz, f.name); }
int gd_vbs_bus(void) { return f.jcibus; }
int gd_vbs_msg_calls(void) { return f.msg_calls; }
int gd_vbs_msg2_calls(void) { return f.msg2_calls; }
unsigned gd_vbs_disp_icon(void) { return f.disp.next_maneuver_info; }
unsigned gd_vbs_disp_distance(void) { return f.disp.distance_value; }
unsigned gd_vbs_disp_unit(void) { return f.disp.distance_unit; }
unsigned gd_vbs_disp_limit(void) { return f.disp.display_speed_limit; }
unsigned gd_vbs_disp_limit_unit(void) { return f.disp.display_speed_unit; }
unsigned gd_vbs_disp_sync(void) { return f.disp.text_id3; }
void gd_vbs_road(char *dst, unsigned sz) { copy_str(dst, sz, f.road); }
unsigned gd_vbs_msg2_sync(void) { return f.msg2_sync; }
void gd_vbs_last_log(char *dst, unsigned sz)
{
    copy_str(dst, sz, f.log_count ? f.logs[f.log_count - 1] : "");
}
void gd_vbs_set_fail(int which, int on)
{
    if (which == 0)
        f.fail_create = on;
    else if (which == 1)
        f.fail_connect = on;
    else if (which == 2)
        f.fail_msg = on;
    else
        f.fail_msg2 = on;
}
void gd_vbs_set_status(unsigned char status) { f.status_reply = status; }
void gd_vbs_unbind(void) { vn_vbs_bind(0); }
