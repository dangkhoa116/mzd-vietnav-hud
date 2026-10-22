/* SPDX-License-Identifier: AGPL-3.0-or-later */
#ifndef VIETNAV_VN_VBS_H
#define VIETNAV_VN_VBS_H
#include <stdint.h>
#include "hud_guidance.h"

/* Sender that pushes guidance records to the car's com.jci.vbs.navi service
 * through the OEM's own client libraries (libjcidbus + libjcivbsnaviclient).
 * ABI notes and field offsets are hand-derived in
 * mazda-carplay-hud/patches/blmjcicarplay/oem (Ghidra decompile of the CMU
 * 70.x libs; same author, AGPL-3.0-or-later).
 *
 * vn_vbs.c is plain logic plus an injectable backend so host tests run with
 * fakes and no D-Bus. The real backend lives in vn_vbs_dl.c (dlopen), which
 * the car build compiles in and binds via vn_vbs_bind_dl().
 */

/* com.jci.vbs.navi HUD frame, D-Bus signature (uqyqyy): u32@0, u16@4,
 * u8@6, u16@8, u8@10, u8@11; sizeof == 12 (natural pad at 7). */
struct vn_vbs_display {
    uint32_t next_maneuver_info;
    uint16_t distance_value;
    uint8_t distance_unit;
    uint16_t display_speed_limit;
    uint8_t display_speed_unit;
    uint8_t text_id3; /* sync bit */
};

/* Street strip, signature (sy): char*@0, u8@8. The OEM library transcodes
 * UTF-8 -> UCS-2 and pages it internally. */
struct vn_vbs_msg2 {
    const char *guidance_point_name;
    uint8_t sync_bit;
};

/* One entry per OEM symbol vn_vbs needs; resolved by vn_vbs_dl.c or faked
 * in tests. conn_create(error_cb, 0) -> handle; conn_connect != 0 on success
 * (it also disables libdbus exit-on-disconnect); the setters return 0 when
 * the message is queued. */
struct vn_vbs_calls {
    void *(*conn_create)(void *error_cb, int reserved);
    int (*conn_connect)(void *conn, const char *name, int jcibus, void *reserved);
    int (*worker_start)(void *conn);
    void (*worker_stop)(void *conn);
    void (*conn_disconnect)(void *conn);
    void (*conn_free)(void *conn);
    int (*set_hud_msg)(void *conn, void *disp, void *unused, void *cb, void *user);
    int (*set_hud_msg2)(void *conn, void *msg2, void *unused, void *cb, void *user);
    int (*get_hud_status)(void *conn, void *cb, void *user);
};

#define VN_VBS_BUS_NAME "com.jci.vietnav.hud"
#define VN_VBS_JCI_SERVICE_BUS 0

/* Install a backend (copies *calls). Passing calls with a NULL conn_create
 * leaves the sender inert. */
void vn_vbs_bind(const struct vn_vbs_calls *calls);
int vn_vbs_bound(void);

/* Optional diagnostic sink (single line, no newline). */
void vn_vbs_set_logger(void (*log)(const char *msg));

/* 1 while an OEM connection is up. */
int vn_vbs_active(void);

/* Push one guidance record (or the wipe when g->clear). Creates the bus
 * connection lazily on the first call. Returns 0 when nothing failed,
 * -1 without a transport or on a rejected send. */
int vn_vbs_guide(const struct vn_guidance *g);

/* Wipe the HUD (clear pair) and release the OEM connection. Safe to call
 * when nothing is connected. */
void vn_vbs_stop(void);

/* Resolved by vn_vbs_dl.c from the on-car libraries. Returns 1 and fills
 * *out on success. Tests never link that file. */
int vn_vbs_dl_resolve(struct vn_vbs_calls *out);
#endif
