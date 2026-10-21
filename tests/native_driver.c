/* SPDX-License-Identifier: AGPL-3.0-or-later */
#include "hud_native.h"
#include <string.h>
static struct vn_hud hud;
static struct vn_caps caps;
static unsigned char packets[256][40];
static unsigned lengths[256], count, at;
static int reject_send;
static int send_packet(void *u, const unsigned char *p, unsigned n) {
  (void)u;
  if (reject_send || count >= 256 || n > 40)
    return 0;
  memcpy(packets[count], p, n);
  lengths[count++] = n;
  return 1;
}
static void record_event(void *u, const char *s, const unsigned char *p,
                         unsigned n) {
  (void)u;
  (void)s;
  (void)p;
  (void)n;
}
void test_reset(void) {
  struct vn_io io = {0, send_packet, record_event};
  memset(&caps, 0, sizeof caps);
  count = at = reject_send = 0;
  vn_init(&hud, io);
}
void test_caps(const unsigned char *commands, const unsigned char *states,
               unsigned size, unsigned number, unsigned seen) {
  memcpy(caps.commands, commands, 64);
  memcpy(caps.states, states, 8);
  caps.acl_size = size;
  caps.acl_count = number;
  caps.commands_seen = !!(seen & 1);
  caps.states_seen = !!(seen & 2);
  caps.buffer_seen = !!(seen & 4);
}
int test_ready(void) { return vn_caps_ready(&caps); }
int test_start(int adv, unsigned long long now, unsigned duration) {
  return vn_start(&hud, &caps, adv, now, duration);
}
void test_tick(unsigned long long now, int allow) { vn_tick(&hud, now, allow); }
void test_reply(unsigned op, unsigned status, unsigned long long now) {
  vn_command_reply(&hud, op, status, now);
}
void test_connect(unsigned status, unsigned h, unsigned role,
                  unsigned long long now) {
  vn_connected(&hud, status, h, role, now);
}
void test_disconnect(unsigned h) { vn_disconnected(&hud, h); }
void test_completed(unsigned h, unsigned n) { vn_completed(&hud, h, n); }
void test_att(const unsigned char *p, unsigned n) { vn_att(&hud, p, n); }
void test_stop(void) { vn_stop(&hud, "test stop"); }
int test_state(void) { return hud.state; }
int test_handle(void) { return hud.handle; }
void test_reject_send(int on) { reject_send = on; }
unsigned test_pop(unsigned char *p) {
  unsigned n;
  if (at == count)
    return 0;
  n = lengths[at];
  memcpy(p, packets[at++], n);
  return n;
}
