// Host test for the oem-aa-mod road-name budget fix (AaGuidance.road 64 -> 256).
// Builds a synthetic GAL 1.6 NavigationState (0x8006) whose road name is a long
// Vietnamese string: >63 raw bytes (the old decode budget) but well within the
// HUD strip after fold(). Verifies:
//   1. hud_nav16_on_frame keeps the FULL raw name (pre-fix it clipped at 63).
//   2. hud_translit::fold() shrinks it to the expected length with no 3-byte
//      precomposed Latin left, i.e. every glyph is HUD-renderable.
// Compile (host, zig cc):
//   python -m ziglang c++ -std=c++17 \
//     -I <oem-aa-mod>/mazda/patches/blmjciaapa/hud \
//     -I <oem-aa-mod>/mazda/patches/common \
//     road_fold_test.cpp <oem-aa-mod>/mazda/patches/blmjciaapa/hud/hud_nav16.cpp \
//     -o road_fold_test.exe
#include "hud_nav16.h"
#include "translit.h"
#include <cstdio>
#include <cstring>

static int failures = 0;
#define CHECK(cond, msg) do { \
    if (!(cond)) { printf("FAIL: %s\n", msg); ++failures; } \
    else { printf("ok:   %s\n", msg); } } while (0)

// minimal protobuf writers
static size_t put_varint(uint8_t *p, uint64_t v) {
    size_t n = 0;
    while (v >= 0x80) { p[n++] = (uint8_t)(v | 0x80); v >>= 7; }
    p[n++] = (uint8_t)v; return n;
}
static size_t put_len(uint8_t *p, uint32_t field, const uint8_t *data, size_t len) {
    size_t n = put_varint(p, ((uint64_t)field << 3) | 2);
    n += put_varint(p + n, len);
    memcpy(p + n, data, len);
    return n + len;
}

int main()
{
    // road name: "Nguyễn " x9 = 9 bytes raw each -> 81 raw bytes (> 63 old budget)
    // fold: ễ(3B) -> ê(2B), so each rep becomes 8 bytes -> 72 bytes folded.
    const char *rep = "Nguyễn ";           // N g u y ễ n ' '  = 4+3+1+1 = 9 bytes
    const int REPS = 9;
    char name[128] = {0};
    for (int i = 0; i < REPS; ++i) strcat(name, rep);
    const size_t raw_len = strlen(name);   // 81
    printf("raw name len=%zu folded-expected=%d\n", raw_len, REPS * 8);

    // NavigationRoad{ name=1 }
    uint8_t road_msg[192];
    size_t road_len = put_len(road_msg, 1, (const uint8_t *)name, raw_len);
    // NavigationStep{ road=2 }
    uint8_t step[224];
    size_t step_len = put_len(step, 2, road_msg, road_len);
    // NavigationState{ steps=1 (repeated) }
    uint8_t body[256];
    size_t body_len = put_len(body, 1, step, step_len);
    // frame: 2-byte BE msgId 0x8006 + body
    uint8_t frame[2 + 256];
    frame[0] = 0x80; frame[1] = 0x06;
    memcpy(frame + 2, body, body_len);

    AaGuidance g;
    uint32_t id = hud_nav16_on_frame(frame, (int)(2 + body_len), &g, nullptr);
    CHECK(id == 0x8006, "frame id 0x8006");
    CHECK(g.n_steps == 1, "one step");
    CHECK(strlen(g.road) == raw_len, "road survives decode at FULL length (no 63B clip)");

    char folded[256];
    strncpy(folded, g.road, sizeof(folded) - 1);
    hud_translit::fold(folded);
    size_t flen = strlen(folded);
    CHECK(flen == REPS * 8, "folded length is 72 (each 3-byte ễ -> 2-byte ê)");
    bool no_3byte = true;
    for (size_t i = 0; i < flen; ++i) if ((uint8_t)folded[i] >= 0xE0) no_3byte = false;
    CHECK(no_3byte, "no 3-byte UTF-8 left after fold (all HUD-renderable)");
    // spot-check first rep: "N g u y ê n  " == 4E 67 75 79 C3 AA 6E 20
    const uint8_t want[8] = {0x4E,0x67,0x75,0x79,0xC3,0xAA,0x6E,0x20};
    CHECK(memcmp(folded, want, 8) == 0, "first rep folds 'Nguyễn ' -> 'Nguyen-' (ê kept)");

    printf(failures ? "RESULT: %d FAILURES\n" : "RESULT: ALL PASS\n", failures);
    return failures ? 1 : 0;
}
