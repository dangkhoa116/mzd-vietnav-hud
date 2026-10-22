/* SPDX-License-Identifier: AGPL-3.0-or-later */
/* Real backend: resolve the OEM symbols at runtime. Compiled into the car
 * and Linux host builds only (needs dlfcn); host tests inject fakes into
 * vn_vbs.c directly and never link this file.
 *
 * bds has neither library resident, so unlike jciCARPLAY (which finds them
 * transitively) both must be dlopened explicitly: libjcidbus first for the
 * connection lifecycle, then libjcivbsnaviclient for the VBS_NAVI setters.
 * RTLD_GLOBAL so the navi client's own DT_NEEDED on libjcidbus resolves.
 */
#include "vn_vbs.h"
#include <dlfcn.h>
#include <stdio.h>

static void *open_first(const char *name)
{
    static const char *const prefixes[] = {"", "/jci/lib/", "/usr/lib/", "/lib/"};
    char path[256];
    unsigned i;
    for (i = 0; i < sizeof prefixes / sizeof *prefixes; i++) {
        void *handle;
        if (!prefixes[i][0])
            handle = dlopen(name, RTLD_NOW | RTLD_GLOBAL);
        else {
            if (snprintf(path, sizeof path, "%s%s", prefixes[i], name) >= (int)sizeof path)
                continue;
            handle = dlopen(path, RTLD_NOW | RTLD_GLOBAL);
        }
        if (handle)
            return handle;
    }
    return 0;
}

static void *sym_on(void *handle, const char *name)
{
    void *found = dlsym(handle, name);
    if (!found)
        found = dlsym(RTLD_DEFAULT, name);
    return found;
}

static void *sym_req(void *dbus_handle, void *navi_handle, const char *name)
{
    void *found = sym_on(navi_handle, name);
    if (!found)
        found = sym_on(dbus_handle, name);
    return found;
}

int vn_vbs_dl_resolve(struct vn_vbs_calls *out)
{
    static struct vn_vbs_calls resolved;
    static int done;
    void *dbus, *navi;
    if (!done) {
        dbus = open_first("libjcidbus.so");
        navi = open_first("libjcivbsnaviclient.so");
        if (!dbus || !navi)
            return 0;
        resolved.conn_create = (void *(*)(void *, int))sym_req(dbus, navi,
                                                               "JCIDBUS_conn_create");
        resolved.conn_connect = (int (*)(void *, const char *, int, void *))sym_req(
            dbus, navi, "JCIDBUS_conn_connect");
        resolved.worker_start = (int (*)(void *))sym_req(dbus, navi, "JCIDBUS_worker_start");
        resolved.worker_stop = (void (*)(void *))sym_req(dbus, navi, "JCIDBUS_worker_stop");
        resolved.conn_disconnect = (void (*)(void *))sym_req(dbus, navi,
                                                             "JCIDBUS_conn_disconnect");
        resolved.conn_free = (void (*)(void *))sym_req(dbus, navi, "JCIDBUS_conn_free");
        resolved.set_hud_msg = (int (*)(void *, void *, void *, void *, void *))sym_req(
            dbus, navi, "VBS_NAVI_SetHUDDisplayMsgReq");
        resolved.set_hud_msg2 = (int (*)(void *, void *, void *, void *, void *))sym_req(
            dbus, navi, "VBS_NAVI_TMC_SetHUD_Display_Msg2");
        resolved.get_hud_status = (int (*)(void *, void *, void *))sym_req(
            dbus, navi, "VBS_NAVI_GetHUDStatus");
        if (!resolved.conn_create || !resolved.conn_connect || !resolved.worker_start ||
            !resolved.worker_stop || !resolved.conn_disconnect || !resolved.conn_free ||
            !resolved.set_hud_msg || !resolved.set_hud_msg2 || !resolved.get_hud_status)
            return 0;
        done = 1;
    }
    *out = resolved;
    return 1;
}
