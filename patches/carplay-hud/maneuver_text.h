// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Fallback: derive a HUD turn event from the maneuver INSTRUCTION TEXT when the
// CarPlay app does not give a usable CPManeuverType.
//
// Why this exists
// ---------------
// `nav.cpp` classifies a maneuver from `maneuverType` (@0x128 of the iAP2 0x8059
// burst) and drops anything `is_context_type()` matches — which includes type 0
// (NoTurn). That is correct for an app that fills the field in.
//
// `CPManeuver.maneuverType` only exists since iOS 17.4, and an app is free to
// never set it: a CarPlay nav app can legally ship maneuvers carrying only
// `instructionVariants` (text) + `symbolImage` (a rendered arrow). VIETMAP LIVE
// 3.4.3 is exactly such an app — its plugin binary has `setInstructionVariants:`
// and `setSymbolImage:` but no `setManeuverType:` at all. Every one of its
// maneuvers therefore arrives as type 0 and is discarded, so the HUD stays blank
// while Google Maps (which does set the type) works.
//
// Update 2026-10-25: at RUN time the app does assign maneuverType through KVC
// (`setValue:forKey:@"maneuverType"`, see docs/iphone-probe-results.vi.md §14) —
// the selector is simply not compiled in. Whether that value survives into the
// iAP2 0x8059 burst is exactly what the debug kit measures; this fallback only
// fires when the value on the wire is really 0, so it stays correct either way.
//
// The text is still there, so recover the turn from it. This is additive: it
// only runs where the bridge would otherwise display nothing.
//
// Deliberately NOT a general translator: it answers one question — "is this
// string a turn instruction, and which way?" — and says no when unsure, so a
// road-following line never paints a bogus arrow.
//
// Wording source
// --------------
// The turn phrases below are not guesses any more. They were read out of the
// app itself: VIETMAP LIVE 3.4.3's Dart AOT snapshot
// (Payload/Runner.app/Frameworks/App.framework/App) stores its Vietnamese
// strings as UTF-16LE (Dart TwoByteString — a UTF-8 scan finds nothing), and
// the turn vocabulary there is:
//
//     Rẽ phải / Rẽ trái                    plain turn
//     Rẽ gấp sang phải / ... sang trái     sharp
//     Rẽ hơi lệch sang phải / ... trái     slight      <-- "lệch", NOT "chếch"
//     Tiếp tục đi thẳng                    straight
//     Vào bùng binh và đi theo lối ra thứ  roundabout
//
// Two of those broke the first version of this file: "lệch" was not a keyword
// at all (slight turns would have come out as plain turns), and
// "Tiếp tục đi thẳng" was being vetoed as a road-following line.
//
// Caveat: this is the vocabulary the app ships. The exact string handed to
// `setInstructionVariants:` may still come from the routing API at run time,
// so a car log can still show wording not listed here.

#ifndef VIETNAV_CARPLAY_MANEUVER_TEXT_H
#define VIETNAV_CARPLAY_MANEUVER_TEXT_H

#include <stddef.h>
#include <stdint.h>

namespace maneuver_text {

// --- Vietnamese -> ASCII ------------------------------------------------
//
// Matching happens on a folded, lower-cased copy so one pattern covers every
// accent spelling ("Rẽ phải", "RẼ PHẢI", "Re phai"). Only the letters that
// carry Vietnamese diacritics need mapping; everything else passes through.
inline char base_letter(uint32_t cp)
{
    if (cp < 0x80) {
        // Only letters and digits survive. Punctuation MUST become a separator:
        // leaving it attached ("u-turn", "binh,") breaks every word-anchored
        // pattern below.
        if (cp >= 'A' && cp <= 'Z') return static_cast<char>(cp - 'A' + 'a');
        if ((cp >= 'a' && cp <= 'z') || (cp >= '0' && cp <= '9'))
            return static_cast<char>(cp);
        return ' ';
    }
    if (cp == 0x110 || cp == 0x111) return 'd';                      // Đ đ
    if ((cp >= 0xC0 && cp <= 0xC3) || (cp >= 0xE0 && cp <= 0xE3) ||
        cp == 0x102 || cp == 0x103 || (cp >= 0x1EA0 && cp <= 0x1EB7)) return 'a';
    if (cp == 0xC8 || cp == 0xC9 || cp == 0xCA || cp == 0xE8 || cp == 0xE9 ||
        cp == 0xEA || (cp >= 0x1EB8 && cp <= 0x1EC7)) return 'e';
    if (cp == 0xCC || cp == 0xCD || cp == 0xEC || cp == 0xED ||
        cp == 0x128 || cp == 0x129 || (cp >= 0x1EC8 && cp <= 0x1ECB)) return 'i';
    if ((cp >= 0xD2 && cp <= 0xD5) || (cp >= 0xF2 && cp <= 0xF5) ||
        cp == 0x1A0 || cp == 0x1A1 || (cp >= 0x1ECC && cp <= 0x1EE3)) return 'o';
    if (cp == 0xD9 || cp == 0xDA || cp == 0xF9 || cp == 0xFA ||
        cp == 0x168 || cp == 0x169 || cp == 0x1AF || cp == 0x1B0 ||
        (cp >= 0x1EE4 && cp <= 0x1EF1)) return 'u';
    if (cp == 0xDD || cp == 0xFD || (cp >= 0x1EF2 && cp <= 0x1EF9)) return 'y';
    return ' ';   // anything else is a separator, never part of a keyword
}

// UTF-8 -> folded lower-case ASCII with runs of separators collapsed to one
// space, and a leading/trailing space added so patterns can anchor on words.
// Always NUL-terminates; truncates rather than overflowing.
inline void fold(const char *src, char *out, size_t out_size)
{
    if (!out || out_size == 0) return;
    size_t w = 0;
    bool pending_space = true;   // leading space
    const unsigned char *p = reinterpret_cast<const unsigned char *>(src);
    if (!p) { out[0] = '\0'; return; }

    while (*p && w + 2 < out_size) {
        uint32_t cp;
        int extra;
        if (*p < 0x80)            { cp = *p;          extra = 0; }
        else if ((*p & 0xE0) == 0xC0) { cp = *p & 0x1F; extra = 1; }
        else if ((*p & 0xF0) == 0xE0) { cp = *p & 0x0F; extra = 2; }
        else if ((*p & 0xF8) == 0xF0) { cp = *p & 0x07; extra = 3; }
        else { ++p; continue; }                       // stray continuation byte
        ++p;
        bool truncated = false;
        for (int i = 0; i < extra; ++i) {
            if ((*p & 0xC0) != 0x80) { truncated = true; break; }
            cp = (cp << 6) | (*p & 0x3F);
            ++p;
        }
        if (truncated) continue;

        char c = base_letter(cp);
        if (c == ' ' || c == '\0') { pending_space = true; continue; }
        if (pending_space) { out[w++] = ' '; pending_space = false; }
        out[w++] = c;
    }
    // Trailing space only when something was written, so an empty or
    // punctuation-only line folds to "" and is rejected outright.
    if (w > 0 && w + 1 < out_size) out[w++] = ' ';
    out[w] = '\0';
}

inline bool has(const char *folded, const char *needle)
{
    if (!folded || !needle) return false;
    for (const char *s = folded; *s; ++s) {
        const char *a = s, *b = needle;
        while (*b && *a == *b) { ++a; ++b; }
        if (!*b) return true;
    }
    return false;
}

inline bool has_any(const char *folded, const char *const *needles, size_t count)
{
    for (size_t i = 0; i < count; ++i)
        if (has(folded, needles[i])) return true;
    return false;
}

#define MT_ANY(folded, ...) \
    ([&]{ static const char *const kN[] = { __VA_ARGS__ }; \
          return has_any((folded), kN, sizeof(kN) / sizeof(kN[0])); }())

// Result mirrors nav.cpp's Maneuver, but this header stays dependency-free so it
// can be unit-tested on the host. nav.cpp copies the fields across.
struct TextTurn {
    uint32_t event;   // hu.proto TURN_EVENT
    uint32_t side;    // 1=LEFT 2=RIGHT 3=NONE
};

// hu.proto TURN_EVENT values nav.cpp uses (kept local so the header is standalone).
enum : uint32_t {
    TT_DEPART = 1, TT_NAME_CHANGE = 2, TT_SLIGHT = 3, TT_TURN = 4, TT_SHARP = 5,
    TT_UTURN = 6, TT_ON_RAMP = 7, TT_OFF_RAMP = 8, TT_FORK = 9, TT_MERGE = 10,
    TT_ROUNDABOUT = 13, TT_STRAIGHT = 14, TT_DEST = 19
};
enum : uint32_t { TT_SIDE_LEFT = 1, TT_SIDE_RIGHT = 2, TT_SIDE_NONE = 3 };

// Returns false when the text is not a turn instruction (road-following,
// compass heading, empty, or simply unrecognised). The caller must then keep
// treating the maneuver as context — guessing here would paint a wrong arrow
// for a whole leg.
inline bool classify(const char *desc, TextTurn *out)
{
    if (!desc || !out) return false;
    char f[320];
    fold(desc, f, sizeof(f));
    if (f[0] == '\0' || f[1] == '\0') return false;

    // Road-following / heading wording. NOT an outright reject: "đi theo lối ra
    // bên phải" is a real off-ramp. It only vetoes a bare straight at the end,
    // so "đi tiếp trên đường X" can never become an arrow that sticks for the
    // rest of the leg.
    const bool follows_road =
        MT_ANY(f, " di tiep ", " tiep tuc ", " di theo ", " bam theo ",
                  " continue on ", " head ", " proceed ", " stay on ", " follow ");

    // ...except this one. "Tiếp tục đi thẳng" is a real instruction in the
    // app's own vocabulary, not a road-following line, so it must survive the
    // veto above (which would otherwise reject it for containing "tiep tuc").
    const bool explicit_straight = has(f, " tiep tuc di thang ");

    // Destination / start. Before the left/right tests: "đã đến đích bên phải"
    // is an arrival, not a right turn.
    if (MT_ANY(f, " da den ", " den noi ", " diem den ", " dich den ",
                  " arrive ", " arriving ", " destination ")) {
        out->event = TT_DEST;
        out->side  = MT_ANY(f, " ben trai ", " phia trai ", " on the left ") ? TT_SIDE_LEFT
                   : MT_ANY(f, " ben phai ", " phia phai ", " on the right ") ? TT_SIDE_RIGHT
                   : TT_SIDE_NONE;
        return true;
    }
    if (MT_ANY(f, " bat dau ", " xuat phat ", " khoi hanh ", " depart ", " start ")) {
        out->event = TT_DEPART;
        out->side  = TT_SIDE_NONE;
        return true;
    }

    // U-turn and roundabout before the plain left/right tests: both wordings
    // usually also contain a side word.
    if (MT_ANY(f, " quay dau ", " quay xe ", " u turn ", " uturn ")) {
        out->event = TT_UTURN;
        out->side  = MT_ANY(f, " phai ", " right ") ? TT_SIDE_RIGHT : TT_SIDE_LEFT;
        return true;
    }
    if (MT_ANY(f, " vong xuyen ", " vong xoay ", " bung binh ", " roundabout ", " rotary ")) {
        out->event = TT_ROUNDABOUT;
        out->side  = TT_SIDE_NONE;   // nav.cpp supplies the drive-side glyph bank
        return true;
    }

    const bool left  = MT_ANY(f, " trai ", " left ");
    const bool right = MT_ANY(f, " phai ", " right ");
    if (left == right) {
        // No side, or a contradictory line: only an explicit straight counts,
        // and not when the line is really "keep going along this road".
        if ((explicit_straight || !follows_road) &&
            MT_ANY(f, " di thang ", " thang tien ", " straight ")) {
            out->event = TT_STRAIGHT;
            out->side  = TT_SIDE_NONE;
            return true;
        }
        return false;
    }
    const uint32_t side = left ? TT_SIDE_LEFT : TT_SIDE_RIGHT;

    // Qualifiers before the plain turn: "rẽ phải gấp" contains "re phai".
    if (MT_ANY(f, " gap ", " ngoat ", " sharp "))                 out->event = TT_SHARP;
    // "hoi lech"/"lech sang" is how VIETMAP LIVE words a slight turn ("Rẽ hơi
    // lệch sang phải"). Matched as a pair of words, never bare "lech", so the
    // off-route warning "Bạn đang đi lệch khỏi tuyến đường" cannot trip it.
    else if (MT_ANY(f, " chech ", " hoi lech ", " lech sang ",
                       " slight ", " bear "))                     out->event = TT_SLIGHT;
    else if (MT_ANY(f, " giu lan ", " di theo lan ", " keep ", " fork "))
                                                                  out->event = TT_FORK;
    else if (MT_ANY(f, " nhap lan ", " nhap vao ", " merge "))     out->event = TT_MERGE;
    else if (MT_ANY(f, " loi ra ", " ra khoi ", " exit ", " off ramp "))
                                                                  out->event = TT_OFF_RAMP;
    else if (MT_ANY(f, " duong dan ", " len cao toc ", " on ramp ", " ramp "))
                                                                  out->event = TT_ON_RAMP;
    else if (MT_ANY(f, " re ", " queo ", " turn "))                out->event = TT_TURN;
    else return false;   // a side word alone is not an instruction

    out->side = side;
    return true;
}

#undef MT_ANY

}  // namespace maneuver_text

#endif  // VIETNAV_CARPLAY_MANEUVER_TEXT_H
