/* SPDX-License-Identifier: AGPL-3.0-or-later
 * Experimental single-peripheral HUD. Fixed MTU 23, no bonding, no heap/threads.
 * Run only behind the TPMS HCI mux in HUD-only mode; never a second UART owner.
 */
#include "hud_native.h"

static void zero(void *p, unsigned n)
{
    unsigned char *s = p;
    while (n--)
        *s++ = 0;
}
static void copy(unsigned char *d, const unsigned char *s, unsigned n)
{
    while (n--)
        *d++ = *s++;
}
static unsigned le16(const unsigned char *p)
{
    return p[0] | ((unsigned)p[1] << 8);
}
static void put16(unsigned char *p, unsigned n)
{
    p[0] = n;
    p[1] = n >> 8;
}
static unsigned be32(const unsigned char *p)
{
    return ((unsigned)p[0] << 24) | ((unsigned)p[1] << 16) | ((unsigned)p[2] << 8) | p[3];
}
static void put32(unsigned char *p, uint32_t n)
{
    p[0] = n >> 24;
    p[1] = n >> 16;
    p[2] = n >> 8;
    p[3] = n;
}
static const unsigned char default_uid[16] = {0xf7, 0xfd, 0x15, 0x75, 0x02, 0xda, 0x52, 0x8e,
                                              0xf0, 0xfc, 0x31, 0x39, 0x72, 0x2c, 0xe9, 0xe2};

/* RFC 1321 transform, implemented here to avoid a car libcrypto dependency.
 * Input is data || 16-byte UID; no secret/account identity is embedded.
 */
void vn_checksum(const unsigned char *p, unsigned n, const unsigned char uid[16],
                 unsigned char out[4])
{
    static const uint32_t k[64] = {
        0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee, 0xf57c0faf, 0x4787c62a, 0xa8304613,
        0xfd469501, 0x698098d8, 0x8b44f7af, 0xffff5bb1, 0x895cd7be, 0x6b901122, 0xfd987193,
        0xa679438e, 0x49b40821, 0xf61e2562, 0xc040b340, 0x265e5a51, 0xe9b6c7aa, 0xd62f105d,
        0x02441453, 0xd8a1e681, 0xe7d3fbc8, 0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed,
        0xa9e3e905, 0xfcefa3f8, 0x676f02d9, 0x8d2a4c8a, 0xfffa3942, 0x8771f681, 0x6d9d6122,
        0xfde5380c, 0xa4beea44, 0x4bdecfa9, 0xf6bb4b60, 0xbebfbc70, 0x289b7ec6, 0xeaa127fa,
        0xd4ef3085, 0x04881d05, 0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665, 0xf4292244,
        0x432aff97, 0xab9423a7, 0xfc93a039, 0x655b59c3, 0x8f0ccc92, 0xffeff47d, 0x85845dd1,
        0x6fa87e4f, 0xfe2ce6e0, 0xa3014314, 0x4e0811a1, 0xf7537e82, 0xbd3af235, 0x2ad7d2bb,
        0xeb86d391};
    static const unsigned char shift[16] = {7, 12, 17, 22, 5, 9,  14, 20,
                                            4, 11, 16, 23, 6, 10, 15, 21};
    uint32_t h[4] = {0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476}, w[16], a, b, c, d, f, t;
    unsigned total = n + 16, blocks = (total + 9 + 63) / 64, block, i, j, g, s, pos;
    unsigned char buf[64], digest[16];
    uint64_t bits = (uint64_t)total * 8;
    for (block = 0; block < blocks; block++) {
        for (i = 0; i < 64; i++) {
            pos = block * 64 + i;
            buf[i] = pos < n ? p[pos] : (pos < total ? uid[pos - n] : (pos == total ? 0x80 : 0));
            if (pos >= blocks * 64 - 8)
                buf[i] = (unsigned char)(bits >> (8 * (pos - (blocks * 64 - 8))));
        }
        for (i = 0; i < 16; i++)
            w[i] = (uint32_t)buf[i * 4] | ((uint32_t)buf[i * 4 + 1] << 8) |
                   ((uint32_t)buf[i * 4 + 2] << 16) | ((uint32_t)buf[i * 4 + 3] << 24);
        a = h[0];
        b = h[1];
        c = h[2];
        d = h[3];
        for (i = 0; i < 64; i++) {
            if (i < 16) {
                f = (b & c) | (~b & d);
                g = i;
            } else if (i < 32) {
                f = (d & b) | (~d & c);
                g = (5 * i + 1) % 16;
            } else if (i < 48) {
                f = b ^ c ^ d;
                g = (3 * i + 5) % 16;
            } else {
                f = c ^ (b | ~d);
                g = (7 * i) % 16;
            }
            s = shift[(i / 16) * 4 + i % 4];
            t = a + f + k[i] + w[g];
            a = d;
            d = c;
            c = b;
            b += ((t << s) | (t >> (32 - s)));
        }
        h[0] += a;
        h[1] += b;
        h[2] += c;
        h[3] += d;
    }
    for (i = 0; i < 4; i++)
        for (j = 0; j < 4; j++)
            digest[4 * i + j] = (unsigned char)(h[i] >> (8 * j));
    put32(out, be32(digest) + be32(digest + 4) + be32(digest + 8) + be32(digest + 12));
}

static void record(struct vn_hud *v, const char *s, const unsigned char *p, unsigned n)
{
    if (v->io.record)
        v->io.record(v->io.user, s, p, n);
}
void vn_init(struct vn_hud *v, struct vn_io io)
{
    zero(v, sizeof *v);
    v->io = io;
    v->handle = -1;
    v->state = VN_OFF;
}

int vn_caps_ready(const struct vn_caps *c)
{
    /* Supported Commands bit numbers from Core HCI table: 205,207,208,209.
     * LE state bit 2 = connectable advertising; bit 7 = peripheral connection.
     * Require a dedicated LE ACL buffer: shared classic ACL pools need a broker.
     */
    return c->commands_seen && c->states_seen && c->buffer_seen &&
           (c->commands[25] & 0xa0) == 0xa0 && (c->commands[26] & 3) == 3 &&
           (c->states[0] & 0x84) == 0x84 && c->acl_size >= 27 && c->acl_count > 0;
}

int vn_start(struct vn_hud *v, const struct vn_caps *c, int advertise, uint64_t now,
             unsigned duration_ms)
{
    record(v, "VML COMMANDS", c->commands, c->commands_seen ? 64 : 0);
    record(v, "VML STATES", c->states, c->states_seen ? 8 : 0);
    if (!vn_caps_ready(c)) {
        v->state = VN_FAILED;
        record(v, "VML RESULT capabilities missing/unsupported", 0, 0);
        return 0;
    }
    if (!advertise) {
        v->state = VN_DONE;
        record(v, "VML RESULT peripheral capability present; query only", 0, 0);
        return 1;
    }
    if (!duration_ms || duration_ms > 180000)
        duration_ms = 60000;
    v->expires = now + duration_ms;
    v->state = VN_CONFIG;
    v->stage = 0;
    record(v, "VML native HUD-only trial", 0, 0);
    return 1;
}

void vn_stop(struct vn_hud *v, const char *reason)
{
    if (v->state == VN_OFF || v->state == VN_DONE || v->state == VN_FAILED)
        return;
    record(v, reason, 0, 0);
    v->state = VN_STOPPING;
    v->head = v->tail = 0;
    v->info_at = v->info_len = v->wire_len = v->cccd = v->tpms_cccd = 0;
}
static void fail(struct vn_hud *v, const char *s)
{
    v->failed = 1;
    vn_stop(v, s);
}

static int command(struct vn_hud *v, unsigned op, const unsigned char *p, unsigned n, uint64_t now)
{
    unsigned char b[36];
    b[0] = 1;
    put16(b + 1, op);
    b[3] = n;
    copy(b + 4, p, n);
    if (!v->io.send(v->io.user, b, n + 4)) {
        if (v->state == VN_STOPPING) {
            v->failed = 1;
            v->cleanup++;
            v->cleanup_pending = 0;
        } else
            fail(v, "VML ABORT UART write");
        return 0;
    }
    v->pending = op;
    v->command_at = v->last_command = now;
    return 1;
}

void vn_command_reply(struct vn_hud *v, unsigned op, unsigned status, uint64_t now)
{
    (void)now;
    if (op != v->pending)
        return;
    v->pending = 0;
    if (status) {
        if (v->state == VN_STOPPING) {
            /* Cleanup is bounded even when the controller refuses an off. */
            record(v, "VML cleanup command refused", 0, 0);
            v->failed = 1;
            if (v->cleanup_pending)
                v->cleanup++;
            v->cleanup_pending = 0;
        } else
            fail(v, "VML ABORT controller rejected advertising command");
        return;
    }
    if (v->state == VN_STOPPING) {
        if (v->cleanup_pending) {
            if (v->cleanup == 0)
                v->adv_maybe_on = 0;
            v->cleanup++;
        }
        v->cleanup_pending = 0;
        return;
    }
    v->stage++;
    if (v->stage == 4 && v->state == VN_CONFIG) {
        v->state = VN_ADVERTISING;
        record(v, "VML advertising " VN_NAME, 0, 0);
    }
}

static void queue(struct vn_hud *v, const unsigned char *p, unsigned n)
{
    if (n > VN_MTU || v->tail - v->head >= VN_QUEUE) {
        fail(v, "VML ABORT ATT queue full");
        return;
    }
    copy(v->queue[v->tail % VN_QUEUE], p, n);
    v->queue_len[v->tail % VN_QUEUE] = n;
    v->tail++;
}
static void reset_link(struct vn_hud *v)
{
    v->cccd = v->tpms_cccd = v->wire_len = v->info_len = v->info_at = v->acl_out = 0;
    v->head = v->tail = 0;
    /* New session: the guidance stream restarts so a reconnected app re-emits
     * its first live frame instead of being deduped against the old route. */
    vn_guide_reset(&v->guide);
}

void vn_connected(struct vn_hud *v, unsigned status, unsigned handle, unsigned role, uint64_t now)
{
    (void)now;
    if (status) {
        record(v, "VML connection failed", 0, 0);
        return;
    }
    if (v->handle >= 0 || role != 1 ||
        (v->state != VN_ADVERTISING &&
         !(v->state == VN_CONFIG && v->pending == 0x200a && v->stage == 3))) {
        if (v->handle < 0) {
            v->handle = (int)handle;
            v->adv_maybe_on = 0;
        }
        fail(v, "VML ABORT unexpected connection role/state");
        return;
    }
    reset_link(v);
    v->handle = (int)handle;
    v->adv_maybe_on = 0;
    v->state = VN_CONNECTED;
    record(v, "VML connected", 0, 0);
}
void vn_disconnected(struct vn_hud *v, unsigned handle)
{
    if (v->handle != (int)handle)
        return;
    v->handle = -1;
    reset_link(v);
    record(v, "VML disconnected", 0, 0);
    /* One connection per trial; do not silently advertise after disconnect. */
    if (v->state != VN_STOPPING)
        v->state = v->failed ? VN_FAILED : VN_DONE;
}
void vn_completed(struct vn_hud *v, unsigned handle, unsigned count)
{
    if (v->handle != (int)handle)
        return;
    if (count >= v->acl_out)
        v->acl_out = 0;
    else
        v->acl_out -= count;
}

void vn_tick(struct vn_hud *v, uint64_t now, int command_allowed)
{
    unsigned char p[32], b[32];
    unsigned n = 0, op = 0, i;
    if (v->state == VN_OFF || v->state == VN_DONE || v->state == VN_FAILED)
        return;
    if (now >= v->expires && v->state != VN_STOPPING)
        vn_stop(v, "VML trial expired");
    if (v->pending) {
        if (now - v->command_at < 3000)
            return;
        v->pending = 0;
        if (v->state == VN_STOPPING) {
            v->failed = 1;
            if (v->cleanup_pending)
                v->cleanup++;
            v->cleanup_pending = 0;
        } else
            fail(v, "VML ABORT command timeout");
    }
    if (v->state == VN_STOPPING) {
        /* Even after an unanswered enable, explicitly request disable once. */
        if (v->cleanup == 0 && !v->adv_maybe_on)
            v->cleanup = 1;
        if (v->cleanup == 1 && v->handle < 0)
            v->cleanup = 2;
        if (v->cleanup >= 2) {
            if (v->handle >= 0) {
                if (now - v->command_at < 3000)
                    return;
                v->failed = 1;
                record(v, "VML disconnect unconfirmed", 0, 0);
            }
            v->state = v->failed ? VN_FAILED : VN_DONE;
            record(v, "VML RESULT trial stopped", 0, 0);
            return;
        }
        /* Cleanup must not wait for the 3-second idle window. One bounded command. */
        if (v->last_command && now - v->last_command < 200)
            return;
        v->cleanup_pending = 1;
        if (v->cleanup == 0) {
            p[0] = 0;
            command(v, 0x200a, p, 1, now);
        } else {
            put16(p, (unsigned)v->handle);
            p[2] = 0x13;
            command(v, 0x0406, p, 3, now);
        }
        return;
    }
    if (v->state == VN_CONFIG) {
        if (!command_allowed || (v->last_command && now - v->last_command < 200))
            return;
        zero(p, sizeof p);
        switch (v->stage) {
        case 0:
            op = 0x2006;
            n = 15;
            put16(p, 0x00a0);
            put16(p + 2, 0x00f0);
            p[13] = 7;
            break;
        case 1: /* flags + complete UUID16 list + complete local name, 20 bytes */
            op = 0x2008;
            n = 32;
            p[0] = 20;
            p[1] = 2;
            p[2] = 1;
            p[3] = 6;
            p[4] = 3;
            p[5] = 3;
            p[6] = 0xf0;
            p[7] = 0xff;
            p[8] = 12;
            p[9] = 9;
            copy(p + 10, (const unsigned char *)VN_NAME, 11);
            break;
        case 2:
            op = 0x2009;
            n = 32;
            break; /* explicit empty scan response */
        case 3:
            op = 0x200a;
            n = 1;
            p[0] = 1;
            v->adv_maybe_on = 1;
            break;
        default:
            fail(v, "VML ABORT bad advertising stage");
            return;
        }
        command(v, op, p, n, now);
        return;
    }
    if (v->state != VN_CONNECTED)
        return;
    if (v->acl_out) {
        if (now - v->acl_at > 5000)
            fail(v, "VML ABORT ACL credit timeout");
        return;
    }
    if (v->head == v->tail && v->cccd && v->info_at < v->info_len) {
        n = v->info_len - v->info_at;
        if (n > 20)
            n = 20;
        b[0] = 0x1b;
        put16(b + 1, 9);
        copy(b + 3, v->info + v->info_at, n);
        queue(v, b, n + 3);
        v->info_at += n;
    }
    if (v->head == v->tail)
        return;
    i = v->head % VN_QUEUE;
    n = v->queue_len[i];
    b[0] = 2;
    put16(b + 1, (unsigned)v->handle | 0x2000);
    put16(b + 3, n + 4);
    put16(b + 5, n);
    put16(b + 7, 4);
    copy(b + 9, v->queue[i], n);
    if (!v->io.send(v->io.user, b, n + 9)) {
        fail(v, "VML ABORT ACL write");
        return;
    }
    v->head++;
    v->acl_out++;
    v->acl_at = now;
}

/* Small static GATT database; 16-bit UUIDs and no dynamic/bonded attributes. */
static const uint16_t types[18] = {0,      0x2800, 0x2803, 0x2a00, 0x2803, 0x2a01,
                                   0x2800, 0x2800, 0x2803, 0xfff1, 0x2902, 0x2803,
                                   0xfff2, 0x2803, 0xfff3, 0x2803, 0xfff4, 0x2902};
static unsigned group_end(unsigned h)
{
    return h == 1 ? 5 : (h == 6 ? 6 : 17);
}
static unsigned value(struct vn_hud *v, unsigned h, unsigned char *p)
{
    static const unsigned char decl[6][5] = {{2, 3, 0, 0, 0x2a},        {2, 5, 0, 1, 0x2a},
                                             {0x12, 9, 0, 0xf1, 0xff},  {0x0c, 12, 0, 0xf2, 0xff},
                                             {0x0c, 14, 0, 0xf3, 0xff}, {0x10, 16, 0, 0xf4, 0xff}};
    unsigned index;
    if (h == 1 || h == 6 || h == 7) {
        put16(p, h == 1 ? 0x1800 : (h == 6 ? 0x1801 : 0xfff0));
        return 2;
    }
    if (h == 2 || h == 4 || h == 8 || h == 11 || h == 13 || h == 15) {
        index = h == 2 ? 0 : (h == 4 ? 1 : (h == 8 ? 2 : (h == 11 ? 3 : (h == 13 ? 4 : 5))));
        copy(p, decl[index], 5);
        return 5;
    }
    if (h == 3) {
        copy(p, (const unsigned char *)VN_NAME, 11);
        return 11;
    }
    if (h == 5 || h == 10 || h == 17) {
        put16(p, h == 5 ? 0 : (h == 10 ? v->cccd : v->tpms_cccd));
        return 2;
    }
    return 0;
}
static int readable(unsigned h)
{
    return h && h < 18 && h != 12 && h != 14 && h != 16;
}
static void error(struct vn_hud *v, unsigned opcode, unsigned h, unsigned code)
{
    unsigned char p[5] = {1, 0, 0, 0, 0};
    p[1] = opcode;
    put16(p + 2, h);
    p[4] = code;
    queue(v, p, 5);
}

static void wire_frame(struct vn_hud *v, const unsigned char *p, unsigned n)
{
    unsigned char sum[4], cmd;
    unsigned i;
    /* Exact identity the iOS app accepted on the ESP32-C3 trial (2026-10-22):
     * PROTOCOL without the trailing "S" - "2.2.2S" forces the no-image CMD 0x00
     * branch in insideSendCustomNavigation and the HUD would never get arrows. */
    static const unsigned char text[] =
        "MODEL:H50,HW:1.0.0,FW:1.0.0,PROTOCOL:2.2.2,OBDV:0_1.0,SID:VMEMU0000001";
    static const unsigned char zero_uid[16] = {0};
    vn_checksum(p, n - 8, default_uid, sum);
    for (i = 0; i < 4; i++)
        if (sum[i] != p[n - 4 + i]) {
            record(v, "VML invalid checksum", 0, 0);
            return;
        }
    cmd = p[12];
    record(v, "VML FRAME CMD", &cmd, 1);
    if (cmd == 0 || cmd == 0x40) {
        /* Navigation push (0x00 = layouts v1/fixed, 0x40 = variable v2 with
         * the JPEG arrow). Icon hint stays 0 here: classifying the arrow
         * image needs the offline fingerprint set, so the HUD holds the last
         * icon (straight initially) - distance/road/clear are all live. */
        struct vn_nav nav;
        struct vn_guidance guidance;
        if (vn_nav_decode(&nav, p + 12, n - 20) && v->io.guide) {
            if (vn_guide_feed(&v->guide, &guidance, &nav, 0))
                v->io.guide(v->io.user, &guidance);
        }
        return;
    }
    if (cmd != 14 || n != 22 || p[13] != 0)
        return;
    if (v->info_at < v->info_len) {
        record(v, "VML duplicate info request while reply pending", 0, 0);
        return;
    }
    copy(v->info, p, 4);
    put32(v->info + 4, (unsigned)sizeof(text) - 1 + 13);
    copy(v->info + 8, p + 8, 4);
    v->info[12] = 14;
    copy(v->info + 13, text, sizeof(text) - 1);
    i = 13 + sizeof(text) - 1;
    vn_checksum(v->info, i, zero_uid, v->info + i);
    vn_checksum(v->info, i, default_uid, v->info + i + 4);
    v->info_len = i + 8;
    v->info_at = 0;
    record(v, "VML info reply queued", 0, 0);
}
static void wire_bytes(struct vn_hud *v, const unsigned char *p, unsigned n)
{
    unsigned size, i;
    record(v, "VML RX", p, n);
    while (n--) {
        if (v->wire_len >= VN_FRAME_MAX) {
            v->wire_len = 0;
            record(v, "VML frame too large", 0, 0);
        }
        v->wire[v->wire_len++] = *p++;
        while (v->wire_len >= 4 && (v->wire[0] != 0xa5 || v->wire[1] != 0x5a ||
                                    v->wire[2] != 0x37 || v->wire[3] != 0xc3)) {
            for (i = 1; i < v->wire_len; i++)
                v->wire[i - 1] = v->wire[i];
            v->wire_len--;
        }
        if (v->wire_len < 8)
            continue;
        size = be32(v->wire + 4);
        if (size < 13 || size > VN_FRAME_MAX - 8) {
            v->wire_len = 0;
            record(v, "VML invalid frame length", 0, 0);
            continue;
        }
        size += 8;
        if (v->wire_len == size) {
            wire_frame(v, v->wire, size);
            v->wire_len = 0;
        }
    }
}

void vn_att(struct vn_hud *v, const unsigned char *p, unsigned n)
{
    unsigned op, h, end, type, i, len, off = 0, w = 0, size = 0;
    unsigned char out[VN_MTU], tmp[16];
    if (v->state != VN_CONNECTED || !n)
        return;
    op = p[0];
    if (n > VN_MTU) {
        if (!(op & 0x40))
            error(v, op, 0, 4);
        return;
    }
    if (op == 2) {
        if (n != 3 || le16(p + 1) < 23) {
            error(v, op, 0, 4);
            return;
        }
        out[0] = 3;
        put16(out + 1, VN_MTU);
        queue(v, out, 3);
        return;
    }
    if (op == 0x12 || op == 0x52) {
        if (n < 3) {
            if (op == 0x12)
                error(v, op, 0, 4);
            return;
        }
        h = le16(p + 1);
        if (h == 10 || h == 17) {
            if (n != 5) {
                if (op == 0x12)
                    error(v, op, h, 0x0d);
                return;
            }
            if (le16(p + 3) > 1) {
                if (op == 0x12)
                    error(v, op, h, 0x13);
                return;
            }
            if (h == 10) {
                v->cccd = le16(p + 3);
                if (!v->cccd)
                    v->info_len = v->info_at = 0;
            } else
                v->tpms_cccd = le16(p + 3);
        } else if (h == 12 || h == 14)
            wire_bytes(v, p + 3, n - 3);
        else {
            if (op == 0x12)
                error(v, op, h, h < 18 && h ? 3 : 1);
            return;
        }
        if (op == 0x12) {
            out[0] = 0x13;
            queue(v, out, 1);
        }
        return;
    }
    if (op == 0x0a || op == 0x0c) {
        if (n != (op == 0x0a ? 3u : 5u)) {
            error(v, op, 0, 4);
            return;
        }
        h = le16(p + 1);
        if (!readable(h)) {
            error(v, op, h, h && h < 18 ? 2 : 1);
            return;
        }
        len = value(v, h, tmp);
        if (op == 0x0c)
            off = le16(p + 3);
        if (off > len) {
            error(v, op, h, 7);
            return;
        }
        out[0] = op + 1;
        copy(out + 1, tmp + off, len - off);
        queue(v, out, len - off + 1);
        return;
    }
    if (op != 4 && op != 6 && op != 8 && op != 0x10) {
        if (!(op & 0x40) && op != 0x1e)
            error(v, op, 0, 6);
        return;
    }
    if (n < 5) {
        error(v, op, 0, 4);
        return;
    }
    h = le16(p + 1);
    end = le16(p + 3);
    if (!h || end < h) {
        error(v, op, h, 1);
        return;
    }
    if (op == 4 && n != 5) {
        error(v, op, h, 4);
        return;
    }
    if ((op == 8 || op == 0x10) && n != 7 && n != 21) {
        error(v, op, h, 4);
        return;
    }
    if (op == 6 && n < 9) {
        error(v, op, h, 4);
        return;
    }
    if ((op == 8 || op == 0x10) && n == 21) {
        error(v, op, h, 0x0a);
        return;
    }
    type = op == 4 ? 0 : le16(p + 5);
    if (op == 0x10 && type != 0x2800 && type != 0x2801) {
        error(v, op, h, 0x10);
        return;
    }
    out[0] = op + 1;
    w = (op == 6) ? 1 : 2;
    if (op == 4)
        out[1] = 1;
    for (i = h; i <= end && i < 18; i++) {
        if (op == 4) {
            if (w + 4 > VN_MTU)
                break;
            put16(out + w, i);
            put16(out + w + 2, types[i]);
            w += 4;
            continue;
        }
        if (type != types[i])
            continue;
        len = value(v, i, tmp);
        if (op == 6) {
            if (n - 7 != len)
                continue;
            for (off = 0; off < len && p[7 + off] == tmp[off]; off++) {
            }
            if (off != len)
                continue;
            if (w + 4 > VN_MTU)
                break;
            put16(out + w, i);
            put16(out + w + 2, group_end(i));
            w += 4;
            continue;
        }
        if (!readable(i))
            continue;
        off = (op == 0x10) ? 4 : 2;
        if (size && size != off + len)
            break;
        size = off + len;
        if (w + size > VN_MTU)
            break;
        put16(out + w, i);
        if (off == 4)
            put16(out + w + 2, group_end(i));
        copy(out + w + off, tmp, len);
        w += size;
        out[1] = size;
    }
    if (w == ((op == 6) ? 1u : 2u)) {
        error(v, op, h, 0x0a);
        return;
    }
    queue(v, out, w);
}
