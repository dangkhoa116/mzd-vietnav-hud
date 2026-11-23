/* SPDX-License-Identifier: AGPL-3.0-or-later */
#include "hud_native.h"
#include <string.h>
#ifdef VN_TEST_ARROWS
#include "hud_arrow.h"
#include "vn_vbs.h"
static const unsigned char *arrow_model;
static unsigned arrow_size;
static unsigned match_arrow(void *user, const unsigned char *image, unsigned n) {
  struct vn_arrow_result result;
  (void)user;
  return vn_arrow_match(arrow_model, arrow_size, image, n, &result) ? result.icon : 0;
}
void test_bind_arrow_model(const unsigned char *p, unsigned n);
#endif
static struct vn_hud hud;
static struct vn_caps caps;
static unsigned char packets[4096][40];
static unsigned lengths[4096], count, at;
static int reject_send;
static int send_packet(void *u, const unsigned char *p, unsigned n) {
  (void)u;
  if (reject_send || count >= 4096 || n > 40)
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
static struct vn_guidance guides[64];
static unsigned guide_count, guide_at;
static void guide_event(void *u, const struct vn_guidance *g) {
  (void)u;
  if (guide_count < 64)
    guides[guide_count++] = *g;
#ifdef VN_TEST_ARROWS
  vn_vbs_guide(g);
#endif
}
void test_reset(void) {
  struct vn_io io = {0, send_packet, record_event, guide_event};
  memset(&caps, 0, sizeof caps);
  count = at = reject_send = 0;
  guide_count = guide_at = 0;
  vn_init(&hud, io);
}
#ifdef VN_TEST_ARROWS
void test_bind_arrow_model(const unsigned char *p, unsigned n) {
  arrow_model=p;arrow_size=n;
  vn_set_arrow_matcher(&hud,match_arrow,0);
}
#endif
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
unsigned test_guide_count(void) { return guide_count; }
const struct vn_guidance *test_guide_at(unsigned i) {
  return i < guide_count ? &guides[i] : 0;
}
