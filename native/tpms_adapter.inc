/* SPDX-License-Identifier: AGPL-3.0-or-later
 * Included in a generated copy of MIT-licensed TPMS v3.c, after env_ul().
 * The source checkout is never edited. All UART I/O still uses its mux/lock.
 */
static int vn_same(const char *a, const char *b)
{
    if (!a)
        return 0;
    while (*a && *a == *b) {
        a++;
        b++;
    }
    return *a == *b;
}

static int vn_send_packet(void *user, const unsigned char *p, unsigned n)
{
    (void)user;
    emit_pkt("VML TX HCI", p, n);
    return uart_send(p, n);
}
static void vn_record_packet(void *user, const char *tag, const unsigned char *p, unsigned n)
{
    (void)user;
    if (n)
        emit_pkt(tag, p, n);
    else
        emit_mark(tag);
}
static void vn_guide_out(void *user, const struct vn_guidance *g)
{
    (void)user;
    vn_vbs_guide(g);
}
static void vn_vbs_log_mark(const char *msg)
{
    emit_mark2("VBS ", msg);
}

static void vn_setup(void)
{
    const char *mode = getenv("VIETNAV_NATIVE_MODE");
    struct vn_io io = {0, vn_send_packet, vn_record_packet, vn_guide_out};
    vn_init(&vn_native, io);
    vn_mode = vn_same(mode, "query") ? 1 : (vn_same(mode, "advertise") ? 2 : 0);
    /* This binary has no implicit TPMS mode. No environment = inert preload.
     * Original unit tests can still drive the inherited mux directly.
     */
    if (!vn_mode) {
        st = S_DONE;
        bts_path = 0;
        return;
    }
    vn_vbs_set_logger(vn_vbs_log_mark);
    if (vn_mode == 2) {
        struct vn_vbs_calls calls;
        if (vn_vbs_dl_resolve(&calls))
            vn_vbs_bind(&calls);
        else
            emit_mark("VBS OEM libraries not found; HUD guidance will only be logged");
    }
    stop_after = 0;
    stay = 0;
    one_shot = 0;
    le_first = 0;
    step = ST_CMDS_READ;
    emit_mark("VIETNAV native experimental preload: HUD only, TPMS not running here");
}

static void vn_cap_reply(unsigned which, const unsigned char *p, unsigned n)
{
    unsigned i;
    if (!vn_mode)
        return;
    if (which == ST_CMDS_READ && n >= 71) {
        for (i = 0; i < 64; i++)
            vn_cap.commands[i] = p[7 + i];
        vn_cap.commands_seen = 1;
    }
    if (which == ST_LE_BUF && n >= 10) {
        vn_cap.acl_size = p[7] | ((unsigned)p[8] << 8);
        vn_cap.acl_count = p[9];
        vn_cap.buffer_seen = 1;
        emit_mark_u("VML LE ACL size: ", vn_cap.acl_size);
        emit_mark_u("VML LE ACL count: ", vn_cap.acl_count);
    }
    if (which == ST_LE_STATES) {
        if (n >= 15) {
            for (i = 0; i < 8; i++)
                vn_cap.states[i] = p[7 + i];
            vn_cap.states_seen = 1;
        }
        vn_started = 1;
        st = S_DONE;
        vn_start(&vn_native, &vn_cap, vn_mode == 2, now_ms(),
                 (unsigned)env_ul("VIETNAV_NATIVE_TRIAL_MS", 60000));
    }
}

static void vn_native_tick(void)
{
    uint64_t now = now_ms();
    alive_tick(now);
    pulse_tick(now, 0);
    vn_tick(&vn_native, now, inj_armed(now));
    our_handle = vn_native.handle;
    /* Link gone or trial winding down: wipe the HUD once and release the
     * OEM service bus. The cluster keeps the last frame across sessions,
     * and nothing else clears it for us. */
    if (vn_vbs_active() && vn_native.state != VN_CONNECTED)
        vn_vbs_stop();
}
static void vn_native_reply(const unsigned char *p, unsigned n)
{
    unsigned op, status;
    if (n >= 7 && p[1] == 0x0e) {
        op = p[4] | ((unsigned)p[5] << 8);
        status = p[6];
    } else if (n >= 7 && p[1] == 0x0f) {
        op = p[5] | ((unsigned)p[6] << 8);
        status = p[3];
    } else
        return;
    vn_command_reply(&vn_native, op, status, now_ms());
}
static void vn_native_connect(const unsigned char *p, unsigned n)
{
    if (n < 22) {
        vn_stop(&vn_native, "VML ABORT short connection event");
        return;
    }
    vn_connected(&vn_native, p[4], (p[5] | ((unsigned)p[6] << 8)) & 0xfff, p[7], now_ms());
    our_handle = vn_native.handle;
}
static void vn_native_credits(const unsigned char *p, unsigned n)
{
    unsigned i, count;
    if (!vn_started || n < 4 || p[0] != 4 || p[1] != 0x13)
        return;
    count = p[3];
    if (n != 4 + 4 * count)
        return;
    for (i = 0; i < count; i++)
        vn_completed(&vn_native, (p[4 + i * 4] | ((unsigned)p[5 + i * 4] << 8)) & 0xfff,
                     p[6 + i * 4] | ((unsigned)p[7 + i * 4] << 8));
}
