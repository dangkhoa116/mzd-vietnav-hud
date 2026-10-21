/* SPDX-License-Identifier: AGPL-3.0-or-later */
#include "hud_native.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static unsigned seed = 7;
static unsigned rnd(void) {
  seed = seed * 1664525u + 1013904223u;
  return seed;
}
static int send_packet(void *u, const unsigned char *p, unsigned n) {
  (void)u;
  assert(n <= 36);
  assert(p[0] == 1 || p[0] == 2);
  return 1;
}
int main(void) {
  static struct vn_hud v;
  struct vn_io io = {0, send_packet, 0};
  struct vn_caps cap;
  unsigned i, j, n;
  unsigned char bytes[40], sum[4], uid[16] = {0};
  static const unsigned char raw[] = {0xa5, 0x5a, 0x37, 0xc3, 0, 0,  0,
                                      14,   0,    0,    0,    0, 14, 0};
  static const unsigned char expect[] = {0x4d, 0xc6, 0x42, 0x15};
  vn_checksum(raw, sizeof raw, uid, sum);
  assert(!memcmp(sum, expect, 4));
  memset(&cap, 0, sizeof cap);
  cap.commands_seen = cap.states_seen = cap.buffer_seen = 1;
  cap.commands[25] = 0xa0;
  cap.commands[26] = 3;
  cap.states[0] = 0x84;
  cap.acl_size = 27;
  cap.acl_count = 15;
  for (i = 0; i < 50000; i++) {
    vn_init(&v, io);
    assert(vn_start(&v, &cap, 1, 1000, 60000));
    for (j = 0; j < 4; j++) {
      vn_tick(&v, 1200 + j * 200, 1);
      assert(v.pending);
      vn_command_reply(&v, v.pending, 0, 1200 + j * 200);
    }
    vn_connected(&v, 0, 0x41, 1, 2000);
    assert(v.state == VN_CONNECTED);
    n = rnd() % 41;
    for (j = 0; j < n; j++)
      bytes[j] = (unsigned char)(rnd() >> 24);
    if (i < 256 && n)
      bytes[0] = (unsigned char)i;
    vn_att(&v, bytes, n);
    vn_tick(&v, 2001, 1);
    vn_completed(&v, 0x41, 1);
    vn_disconnected(&v, 0x41);
    assert(v.handle == -1);
  }
  puts("native checksum + 50000 malformed ATT inputs: PASS");
  return 0;
}
