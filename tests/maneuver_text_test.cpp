// Host test for patches/carplay-hud/maneuver_text.h — the instruction-text
// fallback that recovers a turn when a CarPlay app leaves CPManeuver.maneuverType
// unset (VIETMAP LIVE 3.4.3 does exactly that; Google Maps does not).
//
// Build + run (no toolchain needed beyond the pip package):
//   python -m ziglang c++ -std=c++17 -I ../patches/carplay-hud \
//       maneuver_text_test.cpp -o maneuver_text_test
//   ./maneuver_text_test
#include "maneuver_text.h"

#include <cstdio>
#include <cstring>

using namespace maneuver_text;

static int failures = 0;
static int checks = 0;

static void check(bool ok, const char *what)
{
    ++checks;
    if (!ok) { std::printf("FAIL: %s\n", what); ++failures; }
}

// Expect `desc` to classify as (event, side).
static void expect(const char *desc, uint32_t event, uint32_t side)
{
    TextTurn t{};
    const bool ok = classify(desc, &t);
    ++checks;
    if (!ok || t.event != event || t.side != side) {
        std::printf("FAIL: \"%s\" -> ok=%d ev=%u side=%u (muon ev=%u side=%u)\n",
                    desc, (int)ok, t.event, t.side, event, side);
        ++failures;
    }
}

// Expect `desc` to be refused (context / not an instruction).
static void expect_none(const char *desc)
{
    TextTurn t{};
    const bool ok = classify(desc, &t);
    ++checks;
    if (ok) {
        std::printf("FAIL: \"%s\" le ra phai bi tu choi, nhung ra ev=%u side=%u\n",
                    desc, t.event, t.side);
        ++failures;
    }
}

int main()
{
    // --- fold(): dau tieng Viet phai ve ASCII, va bao quanh bang dau cach ---
    {
        char f[128];
        fold("Rẽ phải", f, sizeof(f));
        check(std::strcmp(f, " re phai ") == 0, "fold giu nguyen tu, bo dau");
        fold("RẼ   PHẢI!!", f, sizeof(f));
        check(std::strcmp(f, " re phai ") == 0, "fold ha chu hoa va gom dau cach");
        fold("Đường Số 7", f, sizeof(f));
        check(std::strcmp(f, " duong so 7 ") == 0, "fold xu ly D gach, giu chu so");
        fold("", f, sizeof(f));
        check(f[0] == '\0', "chuoi rong ra chuoi rong");
        // Khong duoc tran bo dem: ban 8 byte cat bot nhung van NUL-terminated.
        char tiny[8];
        fold("Rẽ phải vào Quốc Lộ 13", tiny, sizeof(tiny));
        check(std::strlen(tiny) < sizeof(tiny), "fold khong tran bo dem nho");
    }

    // --- cac cau that tren man hinh dan duong tieng Viet ---
    expect("Rẽ phải", TT_TURN, TT_SIDE_RIGHT);
    expect("Rẽ trái", TT_TURN, TT_SIDE_LEFT);
    expect("Rẽ phải vào Quốc Lộ 13", TT_TURN, TT_SIDE_RIGHT);
    expect("Rẽ trái tại Đường Số 7", TT_TURN, TT_SIDE_LEFT);
    expect("Quẹo phải", TT_TURN, TT_SIDE_RIGHT);

    // Qualifier phai thang cu re thuong: "re phai gap" co chua "re phai".
    expect("Rẽ phải gấp", TT_SHARP, TT_SIDE_RIGHT);
    expect("Rẽ trái gấp vào hẻm", TT_SHARP, TT_SIDE_LEFT);
    expect("Chếch phải", TT_SLIGHT, TT_SIDE_RIGHT);
    expect("Hơi chếch về bên trái", TT_SLIGHT, TT_SIDE_LEFT);

    // --- chuoi THAT doc tu Dart snapshot cua VIETMAP LIVE 3.4.3 ---
    // (App.framework/App, luu UTF-16LE). Day la tu vung app that su dung,
    // khong phai doan. Hai dong "hoi lech" tung bi ban dau phan loai nham
    // thanh cu re thuong vi tu khoa chi co "chech".
    expect("Rẽ phải", TT_TURN, TT_SIDE_RIGHT);
    expect("Rẽ trái", TT_TURN, TT_SIDE_LEFT);
    expect("Rẽ gấp sang phải", TT_SHARP, TT_SIDE_RIGHT);
    expect("Rẽ gấp sang trái", TT_SHARP, TT_SIDE_LEFT);
    expect("Rẽ hơi lệch sang phải", TT_SLIGHT, TT_SIDE_RIGHT);
    expect("Rẽ hơi lệch sang trái", TT_SLIGHT, TT_SIDE_LEFT);
    expect("Tiếp tục đi thẳng", TT_STRAIGHT, TT_SIDE_NONE);
    expect("Vào bùng binh và đi theo lối ra thứ 2", TT_ROUNDABOUT, TT_SIDE_NONE);

    expect("Quay đầu", TT_UTURN, TT_SIDE_LEFT);
    expect("Quay đầu xe khi có thể", TT_UTURN, TT_SIDE_LEFT);

    expect("Đi vào vòng xuyến", TT_ROUNDABOUT, TT_SIDE_NONE);
    expect("Tại bùng binh, đi lối ra thứ hai", TT_ROUNDABOUT, TT_SIDE_NONE);

    expect("Giữ làn bên phải", TT_FORK, TT_SIDE_RIGHT);
    expect("Nhập làn bên trái", TT_MERGE, TT_SIDE_LEFT);
    expect("Đi theo lối ra bên phải", TT_OFF_RAMP, TT_SIDE_RIGHT);

    expect("Đi thẳng", TT_STRAIGHT, TT_SIDE_NONE);
    expect("Đi thẳng qua ngã tư", TT_STRAIGHT, TT_SIDE_NONE);

    // --- diem den va xuat phat ---
    // "da den dich ben phai" co chua "phai" - khong duoc thanh cu re phai.
    expect("Đã đến đích, bên phải", TT_DEST, TT_SIDE_RIGHT);
    expect("Đến nơi", TT_DEST, TT_SIDE_NONE);
    expect("Bắt đầu hành trình", TT_DEPART, TT_SIDE_NONE);

    // --- tieng Anh, phong khi app chay ngon ngu khac ---
    expect("Turn right", TT_TURN, TT_SIDE_RIGHT);
    expect("Turn left onto Main Street", TT_TURN, TT_SIDE_LEFT);
    expect("Sharp left", TT_SHARP, TT_SIDE_LEFT);
    expect("Slight right", TT_SLIGHT, TT_SIDE_RIGHT);
    expect("Make a U-turn", TT_UTURN, TT_SIDE_LEFT);
    expect("Keep right", TT_FORK, TT_SIDE_RIGHT);
    expect("Arrive at destination", TT_DEST, TT_SIDE_NONE);

    // --- phai TU CHOI: bam duong, huong la ban, rac ---
    // Day la phan quan trong nhat: doan bua o day se dan mot mui ten sai suot
    // ca chang duong.
    expect_none("Đi tiếp trên Quốc Lộ 13");
    // "Bạn đang đi lệch khỏi tuyến đường" la canh bao LECH TUYEN, khong phai
    // cu re. Day la ly do tu khoa slight la " hoi lech "/" lech sang " chu
    // khong phai " lech " tran.
    expect_none("Bạn đang đi lệch khỏi tuyến đường");
    expect_none("Đi theo Đường Số 1");
    expect_none("Continue on Highway 13");
    expect_none("Head north");
    expect_none("Quốc Lộ 13");          // chi la ten duong
    expect_none("");
    expect_none(nullptr);
    expect_none("bên trái");            // chi co tu chi huong, khong phai lenh
    expect_none("Rẽ trái hay rẽ phải");  // mau thuan hai huong

    std::printf("%d kiem tra, %d loi\n", checks, failures);
    return failures ? 1 : 0;
}
