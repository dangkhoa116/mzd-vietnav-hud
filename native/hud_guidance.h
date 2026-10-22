/* SPDX-License-Identifier: AGPL-3.0-or-later */
#ifndef VIETNAV_HUD_GUIDANCE_H
#define VIETNAV_HUD_GUIDANCE_H
#include <stdint.h>

/* Guidance pipeline for the native HUD trial: decode the navigation payloads
 * the VIETMAP LIVE app writes over BLE (layouts proven by static analysis,
 * bridge/vmlhud_nav.py) and fold them into Mazda HUD guidance records that
 * vn_vbs.c pushes to com.jci.vbs.navi. Freestanding: no OS/libc, like
 * hud_native.c, so the same code drives host tests and the CMU build.
 */

#define VN_ROAD_MAX 256
/* App layout bound for one road field (fixed 0xAF layout cuts at 0x50). */
#define VN_ROAD_FIELD_MAX 0x50
#define VN_NAV_FIXED_LEN 0xAF
#define VN_IDLE_DISTANCE 0xFFFFFFFFu
#define VN_KM_THRESHOLD_M 1000u
#define VN_UNIT_METERS 1u
#define VN_UNIT_KM 3u
#define VN_ICON_CLEAR 0u
#define VN_ICON_STRAIGHT 1u

enum vn_nav_layout { VN_NAV_NONE = 0, VN_NAV_FIXED, VN_NAV_VAR1, VN_NAV_VAR2 };

struct vn_nav {
    uint32_t distance_m;
    uint32_t remain_time_s; /* hours*3600 + minutes*60 + raw third byte */
    uint32_t remain_dist_m;
    uint32_t speed_kmh; /* observed; still unconfirmed on the wire */
    uint32_t speed_limit; /* camera/sign feed; 0 until that frame is decoded */
    uint8_t direction;  /* always 0xFE on iOS 3.4.3; kept for the log */
    uint8_t layout;     /* enum vn_nav_layout */
    char next_road[VN_ROAD_MAX];
    char current_road[VN_ROAD_MAX];
};

struct vn_guidance {
    uint32_t icon;        /* Mazda HUD code; VN_ICON_CLEAR = wipe */
    uint32_t distance;    /* u16 value after the unit choice */
    uint32_t unit;        /* 1 = meters, 3 = km, 0 on clear */
    uint32_t speed_limit; /* km/h; 0 hides the roundel */
    uint32_t sync;        /* rotates 1..7 on every emit */
    uint8_t clear;        /* end-of-guidance wipe */
    char road[VN_ROAD_MAX]; /* VN-normalized UTF-8; empty on clear */
};

struct vn_guide_state {
    uint8_t has_last;
    uint8_t sync;
    uint32_t last_icon, last_distance, last_unit, last_limit;
    char last_road[VN_ROAD_MAX];
};

/* Decode one navigation payload, buf[0] = command byte (0x00 or 0x40).
 * Returns 1 and fills *out on success, 0 when no layout parses. Layout
 * preference mirrors bridge/vmlhud_nav.py decode_nav for the same cmd.
 */
int vn_nav_decode(struct vn_nav *out, const unsigned char *buf, unsigned n);

/* (value, unit) pair for a distance in meters; km uses one decimal like the
 * app (hectometer u16), rounding half-to-even to match the Python bridge. */
uint32_t vn_map_distance(uint32_t distance_m, uint32_t *unit);

/* Normalize Vietnamese UTF-8 for the HUD ECU font: the cluster only renders
 * 1-2 byte sequences, so 3-byte Latin Extended Additional characters are
 * mapped to their closest 2-byte base (dropping the tone mark) and anything
 * else non-renderable becomes '?'. Always NUL-terminates dst; returns the
 * number of bytes written excluding the NUL.
 */
unsigned vn_normalize_vn(const char *src, char *dst, unsigned dst_sz);

void vn_guide_reset(struct vn_guide_state *st);

/* Fold one nav frame into the guidance stream. icon_hint 0 means "no arrow
 * classified" (hold last icon, default straight). Returns 1 when *out holds
 * a record to send (dedup'd, sync bumped), 0 when there is nothing new.
 */
int vn_guide_feed(struct vn_guide_state *st, struct vn_guidance *out,
                  const struct vn_nav *nav, uint32_t icon_hint);
#endif
