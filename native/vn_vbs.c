/* SPDX-License-Identifier: AGPL-3.0-or-later */
#include "vn_vbs.h"
#ifdef VN_VBS_HAVE_UNISTD
#include <unistd.h>
#endif

/* Sender state. The connection is created lazily on the first guidance and
 * torn down by vn_vbs_stop(); all calls arrive on the transport's receive
 * path, which the adapter serializes, so no extra locking is needed. The
 * GetHUDStatus probe is fail-open: only an explicit "no HUD" reply gates
 * sends off, a lost reply never silences the trial (same policy as
 * mazda-carplay-hud hud_send.cpp).
 */
static struct {
    struct vn_vbs_calls calls;
    void *conn;
    volatile int hud_absent; /* written from the OEM worker thread */
    int connect_failed;     /* one shot per session; stop() re-arms it */
    uint8_t sync;
    void (*log)(const char *msg);
} vn_vbs;

static void log_line(const char *msg)
{
    if (vn_vbs.log)
        vn_vbs.log(msg);
}

/* libjcidbus requires a non-NULL connection error callback. With
 * exit-on-disconnect off, a service-bus drop is not fatal: log and wait for
 * the bus to come back. */
static void vn_vbs_error_cb(void *conn, void *closure)
{
    (void)conn;
    (void)closure;
    log_line("service-bus connection error (non-fatal)");
}

/* VBS_NAVI_GetHUDStatus reply: cb(conn, status_byte, user); 0 = no HUD. */
static void vn_vbs_status_cb(void *conn, unsigned char status, void *user)
{
    (void)conn;
    (void)user;
    vn_vbs.hud_absent = status == 0;
    log_line(status ? "HUD present" : "HUD reported absent");
}

void vn_vbs_bind(const struct vn_vbs_calls *calls)
{
    if (calls)
        vn_vbs.calls = *calls;
    else {
        static const struct vn_vbs_calls zero;
        vn_vbs.calls = zero;
    }
    vn_vbs.conn = 0;
    vn_vbs.connect_failed = 0;
    vn_vbs.hud_absent = 0;
}

int vn_vbs_bound(void)
{
    return vn_vbs.calls.conn_create != 0;
}

void vn_vbs_set_logger(void (*log)(const char *msg))
{
    vn_vbs.log = log;
}

int vn_vbs_active(void)
{
    return vn_vbs.conn != 0;
}

static int ensure_conn(void)
{
    if (vn_vbs.conn)
        return 1;
    if (vn_vbs.connect_failed || !vn_vbs_bound())
        return 0;
    vn_vbs.conn = vn_vbs.calls.conn_create(vn_vbs_error_cb, 0);
    if (!vn_vbs.conn) {
        log_line("conn_create failed");
        vn_vbs.connect_failed = 1;
        return 0;
    }
    if (!vn_vbs.calls.conn_connect(vn_vbs.conn, VN_VBS_BUS_NAME, VN_VBS_JCI_SERVICE_BUS,
                                   0)) {
        log_line("service-bus connect failed");
        vn_vbs.calls.conn_free(vn_vbs.conn);
        vn_vbs.conn = 0;
        vn_vbs.connect_failed = 1;
        return 0;
    }
    vn_vbs.calls.worker_start(vn_vbs.conn);
    if (vn_vbs.calls.get_hud_status)
        vn_vbs.calls.get_hud_status(vn_vbs.conn, vn_vbs_status_cb, 0);
    log_line("service bus connected");
    return 1;
}

static int send_pair(const struct vn_vbs_display *disp, const char *road, uint8_t sync)
{
    struct vn_vbs_msg2 msg2;
    /* Msg1 and Msg2 go out as an inseparable pair on every push: the native
     * proxy never sends the street strip without the maneuver frame, and an
     * empty name would make the cluster draw garbage - a space blanks it. */
    if (vn_vbs.calls.set_hud_msg(vn_vbs.conn, (void *)disp, 0, 0, 0)) {
        log_line("SetHUDDisplayMsgReq rejected");
        return -1;
    }
    msg2.guidance_point_name = road;
    msg2.sync_bit = sync;
    if (vn_vbs.calls.set_hud_msg2(vn_vbs.conn, &msg2, 0, 0, 0)) {
        log_line("SetHUD_Display_Msg2 rejected");
        return -1;
    }
    return 0;
}

int vn_vbs_guide(const struct vn_guidance *g)
{
    static const char blank[] = " ";
    struct vn_vbs_display disp;
    unsigned i;
    unsigned char *p;
    if (!g)
        return 0;
    if (!ensure_conn())
        return -1;
    if (vn_vbs.hud_absent)
        return 0; /* drain: keep decoding, send nothing */
    for (i = 0, p = (unsigned char *)&disp; i < sizeof disp; i++, p++)
        *p = 0;
    if (!g->clear) {
        /* A wipe stays all-zero whatever the producer left behind. */
        disp.next_maneuver_info = g->icon;
        disp.distance_value = (uint16_t)g->distance;
        disp.distance_unit = (uint8_t)g->unit; /* live frames always carry 1/3 */
        disp.display_speed_limit = (uint16_t)g->speed_limit;
        disp.display_speed_unit = g->speed_limit ? 1 : 0; /* 1 = km/h */
        disp.text_id3 = (uint8_t)g->sync;
        return send_pair(&disp, g->road[0] ? g->road : blank, (uint8_t)g->sync);
    }
    vn_vbs.sync = vn_vbs.sync % 7u + 1u; /* re-page the strip on the wipe */
    disp.text_id3 = vn_vbs.sync;
    return send_pair(&disp, blank, vn_vbs.sync);
}

void vn_vbs_stop(void)
{
    if (!vn_vbs.conn)
        return;
    if (!vn_vbs.hud_absent) {
        static const struct vn_vbs_display disp; /* all zero = blank HUD */
        vn_vbs.sync = vn_vbs.sync % 7u + 1u;
        send_pair(&disp, " ", vn_vbs.sync);
#ifdef VN_VBS_HAVE_UNISTD
        usleep(50 * 1000); /* let the OEM worker flush before it stops */
#endif
    }
    vn_vbs.calls.worker_stop(vn_vbs.conn);
    vn_vbs.calls.conn_disconnect(vn_vbs.conn);
    vn_vbs.calls.conn_free(vn_vbs.conn);
    vn_vbs.conn = 0;
    vn_vbs.connect_failed = 0; /* a later session may reconnect */
    vn_vbs.hud_absent = 0;
    log_line("service bus released");
}
