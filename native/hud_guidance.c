/* SPDX-License-Identifier: AGPL-3.0-or-later */
#include "hud_guidance.h"

static unsigned be16_(const unsigned char *p)
{
    return ((unsigned)p[0] << 8) | p[1];
}
static uint32_t be32_(const unsigned char *p)
{
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}

/* Copy a NUL-scanned or length-prefixed road field, never splitting a UTF-8
 * sequence and always NUL-terminating. Returns the bytes written. */
static unsigned road_copy(char *dst, const unsigned char *src, unsigned cap,
                          unsigned nul_scanned)
{
    unsigned i = 0;
    if (nul_scanned) {
        while (i < cap && i < VN_ROAD_MAX - 1 && src[i])
            i++;
    } else {
        while (i < cap && i < VN_ROAD_MAX - 1)
            i++;
    }
    while (i > 0 && ((unsigned char)src[i - 1] & 0xc0) == 0x80)
        i--;
    for (cap = 0; cap < i; cap++)
        dst[cap] = (char)src[cap];
    dst[i] = 0;
    return i;
}

/* Each decoder sees the payload WITHOUT the command byte, like the Python
 * bridge, and returns the consumed length or 0 when the shape is wrong. */

static unsigned decode_fixed(struct vn_nav *out, const unsigned char *p, unsigned n)
{
    unsigned hours;
    if (n < VN_NAV_FIXED_LEN)
        return 0;
    out->direction = p[0];
    out->distance_m = be32_(p + 1);
    road_copy(out->next_road, p + 5, VN_ROAD_FIELD_MAX, 1);
    road_copy(out->current_road, p + 0x55, VN_ROAD_FIELD_MAX, 1);
    hours = be16_(p + 0xa5);
    out->remain_time_s = hours * 3600u + (unsigned)p[0xa7] * 60u + p[0xa8];
    out->remain_dist_m = be32_(p + 0xa9);
    out->speed_kmh = be16_(p + 0xad);
    out->layout = VN_NAV_FIXED;
    return VN_NAV_FIXED_LEN;
}

static unsigned decode_tail(struct vn_nav *out, const unsigned char *p, unsigned o,
                            unsigned n)
{
    if (o + 10 > n)
        return 0;
    out->remain_time_s = (unsigned)be16_(p + o) * 3600u + (unsigned)p[o + 2] * 60u +
                         p[o + 3];
    out->remain_dist_m = be32_(p + o + 4);
    out->speed_kmh = be16_(p + o + 8);
    return o + 10;
}

static unsigned decode_var1(struct vn_nav *out, const unsigned char *p, unsigned n)
{
    unsigned ln_next, ln_cur, o;
    if (n < 17)
        return 0;
    out->direction = p[0];
    out->distance_m = be32_(p + 1);
    ln_next = p[5];
    o = 6;
    if (o + ln_next >= n)
        return 0;
    road_copy(out->next_road, p + o, ln_next, 0);
    o += ln_next;
    ln_cur = p[o];
    o++;
    if (o + ln_cur + 10 > n)
        return 0;
    road_copy(out->current_road, p + o, ln_cur, 0);
    o += ln_cur;
    o = decode_tail(out, p, o, n);
    if (!o)
        return 0;
    out->layout = VN_NAV_VAR1;
    return o;
}

static unsigned decode_var2(struct vn_nav *out, const unsigned char *p, unsigned n)
{
    uint32_t image_len;
    unsigned ln_next, ln_cur, o;
    if (n < 22)
        return 0;
    image_len = be32_(p + 1);
    if (image_len == 1) {
        if (p[5] > 1)
            return 0;
        o = 6;
    } else if (image_len > 1) {
        if (image_len > n)
            return 0;
        o = 5 + image_len;
        if (o + 4 > n)
            return 0;
    } else
        return 0;
    out->direction = p[0];
    out->distance_m = be32_(p + o);
    o += 4;
    if (o >= n)
        return 0;
    ln_next = p[o];
    o++;
    if (o + ln_next >= n)
        return 0;
    road_copy(out->next_road, p + o, ln_next, 0);
    o += ln_next;
    ln_cur = p[o];
    o++;
    if (o + ln_cur + 10 > n)
        return 0;
    road_copy(out->current_road, p + o, ln_cur, 0);
    o += ln_cur;
    o = decode_tail(out, p, o, n);
    if (!o)
        return 0;
    out->layout = VN_NAV_VAR2;
    return o;
}

int vn_nav_decode(struct vn_nav *out, const unsigned char *buf, unsigned n)
{
    static const unsigned char order[2][3] = {
        {VN_NAV_VAR1, VN_NAV_VAR2, VN_NAV_FIXED}, /* cmd 0x00 */
        {VN_NAV_VAR2, VN_NAV_VAR1, VN_NAV_FIXED}, /* cmd 0x40 */
    };
    unsigned cmd, i, first_ok = 0, consumed, exact;
    struct vn_nav try;
    if (n < 2)
        return 0;
    cmd = buf[0];
    if (cmd != 0x00 && cmd != 0x40)
        return 0;
    for (i = 0; i < 3; i++) {
        for (consumed = 0; consumed < sizeof try; consumed++)
            ((unsigned char *)&try)[consumed] = 0;
        if (order[cmd == 0x40][i] == VN_NAV_FIXED)
            exact = decode_fixed(&try, buf + 1, n - 1);
        else if (order[cmd == 0x40][i] == VN_NAV_VAR1)
            exact = decode_var1(&try, buf + 1, n - 1);
        else
            exact = decode_var2(&try, buf + 1, n - 1);
        if (!exact)
            continue;
        if (exact == n - 1) {
            *out = try;
            return 1;
        }
        if (!first_ok) {
            first_ok = 1;
            *out = try;
        }
    }
    return first_ok;
}

uint32_t vn_map_distance(uint32_t distance_m, uint32_t *unit)
{
    uint32_t value;
    if (distance_m >= VN_KM_THRESHOLD_M) {
        /* One decimal km like the app shows: hectometers, rounded to even
         * at the half to match bridge/vmlhud_vbs.py round(). */
        value = distance_m / 100u;
        distance_m %= 100u;
        if (distance_m > 50u || (distance_m == 50u && (value & 1u)))
            value++;
        *unit = VN_UNIT_KM;
    } else {
        value = distance_m;
        *unit = VN_UNIT_METERS;
    }
    if (value > 0xffffu)
        value = 0xffffu;
    return value;
}

/* 3-byte Vietnamese codepoint (U+1E00..U+1EFF) -> best 2-byte/ASCII base the
 * HUD font renders, else 0. Ported from mazda-carplay-hud hud_send.cpp
 * normalize_vn (same author, AGPL-3.0-or-later); the NFD decomposition test
 * there showed the cluster font has no combining marks and no Latin
 * Extended Additional glyphs, so the tone mark is dropped on purpose. */
static uint32_t vn_base_cp(uint32_t cp)
{
    switch (cp) {
    case 0x1ea0: case 0x1ea2: return 'A';
    case 0x1ea4: case 0x1ea6: case 0x1ea8: case 0x1eaa: case 0x1eac: return 0x00c2u;
    case 0x1eae: case 0x1eb0: case 0x1eb2: case 0x1eb4: case 0x1eb6: return 0x0102u;
    case 0x1eb8: case 0x1eba: case 0x1ebc: return 'E';
    case 0x1ebe: case 0x1ec0: case 0x1ec2: case 0x1ec4: case 0x1ec6: return 0x00cau;
    case 0x1ec8: case 0x1eca: return 'I';
    case 0x1ecc: case 0x1ece: return 'O';
    case 0x1ed0: case 0x1ed2: case 0x1ed4: case 0x1ed6: case 0x1ed8: return 0x00d4u;
    case 0x1eda: case 0x1edc: case 0x1ede: case 0x1ee0: case 0x1ee2: return 0x01a0u;
    case 0x1ee4: case 0x1ee6: return 'U';
    case 0x1ee8: case 0x1eea: case 0x1eec: case 0x1eee: case 0x1ef0: return 0x01afu;
    case 0x1ef2: case 0x1ef4: case 0x1ef6: case 0x1ef8: return 'Y';
    case 0x1ea1: case 0x1ea3: return 'a';
    case 0x1ea5: case 0x1ea7: case 0x1ea9: case 0x1eab: case 0x1ead: return 0x00e2u;
    case 0x1eaf: case 0x1eb1: case 0x1eb3: case 0x1eb5: case 0x1eb7: return 0x0103u;
    case 0x1eb9: case 0x1ebb: case 0x1ebd: return 'e';
    case 0x1ebf: case 0x1ec1: case 0x1ec3: case 0x1ec5: case 0x1ec7: return 0x00eau;
    case 0x1ec9: case 0x1ecb: return 'i';
    case 0x1ecd: case 0x1ecf: return 'o';
    case 0x1ed1: case 0x1ed3: case 0x1ed5: case 0x1ed7: case 0x1ed9: return 0x00f4u;
    case 0x1edb: case 0x1edd: case 0x1edf: case 0x1ee1: case 0x1ee3: return 0x01a1u;
    case 0x1ee5: case 0x1ee7: return 'u';
    case 0x1ee9: case 0x1eeb: case 0x1eed: case 0x1eef: case 0x1ef1: return 0x01b0u;
    case 0x1ef3: case 0x1ef5: case 0x1ef7: case 0x1ef9: return 'y';
    default: return 0;
    }
}

unsigned vn_normalize_vn(const char *src, char *dst, unsigned dst_sz)
{
    const unsigned char *s = (const unsigned char *)src;
    unsigned di = 0, max, nb = 1;
    uint32_t cp, mapped;
    if (!dst || !dst_sz)
        return 0;
    max = dst_sz - 1;
    if (!s) {
        dst[0] = 0;
        return 0;
    }
    while (*s && di < max) {
        if (!(*s & 0x80)) {
            dst[di++] = (char)*s++;
            continue;
        }
        if ((*s & 0xe0) == 0xc0 && s[1]) {
            if (di + 2 > max)
                break;
            dst[di++] = (char)*s++;
            dst[di++] = (char)*s++;
            continue;
        }
        if ((*s & 0xf0) == 0xe0 && s[1] && s[2]) {
            cp = ((uint32_t)(*s & 0x0f) << 12) | ((uint32_t)(s[1] & 0x3f) << 6) |
                 (s[2] & 0x3f);
            nb = 3;
        } else if ((*s & 0xf8) == 0xf0 && s[1] && s[2] && s[3]) {
            cp = ((uint32_t)(*s & 0x07) << 18) | ((uint32_t)(s[1] & 0x3f) << 12) |
                 ((uint32_t)(s[2] & 0x3f) << 6) | (s[3] & 0x3f);
            nb = 4;
        } else {
            s++;
            continue;
        }
        mapped = nb == 3 ? vn_base_cp(cp) : 0;
        if (mapped && mapped < 0x80u) {
            dst[di++] = (char)mapped;
        } else if (mapped && mapped < 0x800u) {
            if (di + 2 > max)
                break;
            dst[di++] = (char)(0xc0 | (mapped >> 6));
            dst[di++] = (char)(0x80 | (mapped & 0x3f));
        } else {
            dst[di++] = '?';
        }
        s += nb;
    }
    dst[di] = 0;
    return di;
}

void vn_guide_reset(struct vn_guide_state *st)
{
    unsigned i;
    for (i = 0; i < sizeof *st; i++)
        ((unsigned char *)st)[i] = 0;
}

static int ws(char c)
{
    return c == ' ' || c == '\t' || c == '\r' || c == '\n';
}

static int road_equal(const char *a, const char *b)
{
    while (*a && *a == *b) {
        a++;
        b++;
    }
    return *a == *b;
}

int vn_guide_feed(struct vn_guide_state *st, struct vn_guidance *out,
                  const struct vn_nav *nav, uint32_t icon_hint)
{
    const char *road;
    char trimmed[VN_ROAD_MAX];
    unsigned i, start, len;
    uint32_t unit;
    for (i = 0; i < sizeof *out; i++)
        ((unsigned char *)out)[i] = 0;
    if (nav->distance_m >= VN_IDLE_DISTANCE) {
        if (!st->has_last)
            return 0; /* already wiped */
        st->has_last = 0;
        out->clear = 1;
        out->sync = st->sync = st->sync % 7u + 1u;
        return 1;
    }
    /* The street strip shows the road the maneuver turns into. */
    road = nav->next_road[0] ? nav->next_road : nav->current_road;
    for (start = 0; ws(road[start]); start++)
        ;
    for (len = 0; road[len]; len++)
        ;
    while (len > start && ws(road[len - 1]))
        len--;
    for (i = 0; start + i < len && i < VN_ROAD_MAX - 1; i++)
        trimmed[i] = road[start + i];
    trimmed[i] = 0;
    if (!trimmed[0] && !icon_hint)
        return 0; /* nothing to guide on yet */
    vn_normalize_vn(trimmed, out->road, VN_ROAD_MAX);
    out->icon = icon_hint ? icon_hint : (st->has_last ? st->last_icon : VN_ICON_STRAIGHT);
    out->distance = vn_map_distance(nav->distance_m, &unit);
    out->unit = unit;
    out->speed_limit = nav->speed_limit;
    if (st->has_last && st->last_icon == out->icon && st->last_distance == out->distance &&
        st->last_unit == out->unit && st->last_limit == out->speed_limit &&
        road_equal(st->last_road, out->road))
        return 0;
    st->has_last = 1;
    st->last_icon = out->icon;
    st->last_distance = out->distance;
    st->last_unit = out->unit;
    st->last_limit = out->speed_limit;
    for (i = 0; out->road[i]; i++)
        st->last_road[i] = out->road[i];
    st->last_road[i] = 0;
    out->sync = st->sync = st->sync % 7u + 1u;
    return 1;
}
