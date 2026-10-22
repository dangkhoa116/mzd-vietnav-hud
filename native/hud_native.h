/* SPDX-License-Identifier: AGPL-3.0-or-later */
#ifndef VIETNAV_HUD_NATIVE_H
#define VIETNAV_HUD_NATIVE_H
#include <stdint.h>
#include "hud_guidance.h"

#define VN_MTU 23
#define VN_FRAME_MAX 2048
#define VN_QUEUE 16
/* Name proven against VIETMAP LIVE 3.4.3 on iOS: must contain "HUD".
 * Must stay 11 bytes - the advertisement and GAP-name reads copy exactly 11. */
#define VN_NAME "VIETMAP-HUD"
enum vn_state { VN_OFF, VN_CONFIG, VN_ADVERTISING, VN_CONNECTED, VN_STOPPING, VN_DONE, VN_FAILED };

struct vn_caps {
    unsigned char commands[64], states[8];
    unsigned commands_seen, states_seen, buffer_seen;
    unsigned acl_size, acl_count;
};
/* send(): complete H4 packet, bounded/nonblocking transport; return 1 on success.
 * record(): only our data. No pointers remain valid after the callback.
 * guide(): one Mazda HUD guidance record per accepted change (hud_guidance.h);
 * optional - leave NULL when no consumer is attached.
 * All calls are serialized by the transport's receive lock. No OS/libc required.
 */
struct vn_io {
    void *user;
    int (*send)(void *, const unsigned char *, unsigned);
    void (*record)(void *, const char *, const unsigned char *, unsigned);
    void (*guide)(void *, const struct vn_guidance *);
};
struct vn_hud {
    struct vn_io io;
    enum vn_state state;
    unsigned stage, pending, adv_maybe_on, cleanup, cleanup_pending, failed;
    int handle;
    uint64_t expires, command_at, last_command, acl_at;
    unsigned acl_out, cccd, tpms_cccd;
    unsigned head, tail;
    unsigned char queue[VN_QUEUE][VN_MTU];
    unsigned char queue_len[VN_QUEUE];
    unsigned char wire[VN_FRAME_MAX];
    unsigned wire_len;
    struct vn_guide_state guide;
    unsigned char info[128];
    unsigned info_len, info_at;
};

void vn_init(struct vn_hud *, struct vn_io);
int vn_caps_ready(const struct vn_caps *);
int vn_start(struct vn_hud *, const struct vn_caps *, int advertise, uint64_t now,
             unsigned duration_ms);
void vn_tick(struct vn_hud *, uint64_t now, int command_allowed);
void vn_command_reply(struct vn_hud *, unsigned opcode, unsigned status, uint64_t now);
void vn_connected(struct vn_hud *, unsigned status, unsigned handle, unsigned role, uint64_t now);
void vn_disconnected(struct vn_hud *, unsigned handle);
void vn_completed(struct vn_hud *, unsigned handle, unsigned count);
void vn_att(struct vn_hud *, const unsigned char *, unsigned);
void vn_stop(struct vn_hud *, const char *reason);
/* Digest-word checksum used by the supplied VietMap SDK; public wire constant. */
void vn_checksum(const unsigned char *, unsigned, const unsigned char uid[16],
                 unsigned char out[4]);
#endif
