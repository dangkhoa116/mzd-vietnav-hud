// vmhud_emu.ino - ESP32 gia lap thiet bi "VIETMAP HUD" (BLE GATT server).
// Nhap: ESP32-C3 Super Mini (hoac bat ky ESP32 nao) + thu vien NimBLE-Arduino.
//
// Muc dich (docs/vietmap-hud-bridge.md):
//   1. Cho VIETMAP LIVE ket noi vao nhu mot HUD that (service FFF0,
//      FFF1 notify / FFF2 write / FFF3 write / FFF4 notify), de:
//   2. Tra loi getHUDInfo (CMD 0x0E) bang chuoi "MODEL:..,HW:..,FW:..,
//      PROTOCOL:..,OBDV:.._..,SID:<serial>" -> kiem tra buoc cap quyen
//      cua app (nhanh A hay B).
//   3. Ghi log moi khung app ghi vao (dang hex + giai ma dan duong theo
//      layout da chot: bridge/vmlhud_nav.py) -> doi chieu offset runtime.
//
// Cach dung:
//   - Arduino IDE: cai "esp32 by Espressif" (Boards Manager) + thu vien
//     "NimBLE-Arduino" (Library Manager). Board: "ESP32C3 Dev Module",
//     USB CDC On Boot: Enabled (de Serial chay qua cong USB-C cua Super Mini).
//   - Nap, mo Serial Monitor 115200.
//   - Dien thoai: VIETMAP LIVE -> HUD/Bluetooth -> quet -> ket noi "VMHUD-EMU".
//   - Lenh serial: MODEL:<x>  HW:<x>  FW:<x>  PROTOCOL:<x>  SID:<x>  NAME:<x>  STATUS
//
// Vi phan tich tich cuc tai phan mem cua nha san xuat, du an chi dung cho
// muc dich tuong thich thiet bi cua chinh minh (research/interoperability).

#include <NimBLEDevice.h>
#include "mbedtls/md5.h"   // co san trong core esp32

// forward declaration: Arduino tu sinh prototype cho cac ham .ino DAT TRUOC
// dinh nghia struct o duoi, nen phai bao truoc o day.
struct NavInfo;

// ---------------- cau hinh (doi duoc qua serial) ----------------
String g_name     = "VMHUD-EMU";     // phai chua "HUD", KHONG chua "TPMS"
String g_model    = "H50";
String g_hw       = "1.0.0";
String g_fw       = "1.0.0";
// PROTOCOL trong dap getHUDInfo chon hang vi phia app (SDK DJ Android):
//   "1.6" -> ban toi thieu: KHONG gui dan duong (J() tra null), chi heartbeat!
//   "2.2.0"/"2.2.1" -> W7/c; "2.2.2" -> W7/d; "2.2.2S" -> W7/e (day du nhat)
String g_protocol = "2.2.2S";
String g_sid      = "VMEMU0000001";  // serial; nhanh B: dung serial HUD that cua minh

// ---------------- GATT ----------------
// HAI ho thiet bi HUD (tu APK Android, Ma/i.java va Ma/j.java):
//   H1/DJBT: service FFF0 - FFF2 write, FFF1 notify, FFF3 write, FFF4 notify(TPMS)
//   H50    : service FFFF - 9ABC write (byte pipe), 1234 notify
// Emulator expose CA HAI de khong phu thuoc che do app dang chon.
#define SVC_H1   "FFF0"
#define CHR_FFF1 "FFF1"   // notify (H1: dap getHUDInfo o day)
#define CHR_FFF2 "FFF2"   // write (H1 duong chinh)
#define CHR_FFF3 "FFF3"   // write (H1 nhanh khac)
#define CHR_FFF4 "FFF4"   // notify (H1 TPMS)
#define SVC_H50  "FFFF"
#define CHR_9ABC "9ABC"   // write (H50 byte pipe)
#define CHR_1234 "1234"   // notify (H50 dap o day)

NimBLECharacteristic *g_chFFF1;   // notify H1
NimBLECharacteristic *g_ch1234;   // notify H50
bool g_connected = false;

// ---------------- khung A5 5A 37 C3 ----------------
static const uint8_t MAGIC[4] = {0xA5, 0x5A, 0x37, 0xC3};
static const size_t MD5_LEN = 16;

uint8_t g_rxbuf[4096];
size_t g_rxlen = 0;

String hex8(const uint8_t *p, size_t n) {
  String s;
  char buf[4];
  for (size_t i = 0; i < n; i++) {
    sprintf(buf, "%02X", p[i]);
    s += buf;
    if (i % 32 == 31 && i + 1 < n) s += "\n";
  }
  return s;
}

// MD5(magic..payload), giong vmlhud_frame.build
size_t build_frame(uint8_t cmd, const uint8_t *payload, size_t plen, uint8_t *out) {
  size_t o = 0;
  memcpy(out, MAGIC, 4); o += 4;
  uint32_t len = plen + 13;
  out[o++] = len >> 24; out[o++] = len >> 16; out[o++] = len >> 8; out[o++] = len;
  uint32_t ts = (uint32_t)time(nullptr);
  out[o++] = ts >> 24; out[o++] = ts >> 16; out[o++] = ts >> 8; out[o++] = ts;
  out[o++] = cmd;
  if (plen) memcpy(out + o, payload, plen);
  o += plen;
  uint8_t dg[16];
  mbedtls_md5(out, o, dg);
  memcpy(out + o, dg, 16);
  return o + 16;
}

void notify_frame(uint8_t cmd, const uint8_t *payload, size_t plen) {
  if (!g_connected) return;
  static uint8_t fr[512];
  size_t n = build_frame(cmd, payload, plen, fr);
  if (n > 512) { Serial.println("[EMU] frame qua dai, bo qua"); return; }
  if (g_chFFF1) g_chFFF1->notify(fr, n);
  if (g_ch1234) g_ch1234->notify(fr, n);
  Serial.printf("[EMU] notify CMD 0x%02X (%d byte payload): %s\n",
                cmd, (int)plen, hex8(payload, plen).c_str());
}

// ---------------- giai ma payload dan duong (port tu vmlhud_nav.py) ----------------
struct NavInfo {
  int direction = 0, distance_m = 0, remain_s = 0, remain_m = 0, speed = 0;
  String cur, nxt;
  const char *layout = "";
};

uint32_t be32(const uint8_t *p) { return ((uint32_t)p[0] << 24) | (p[1] << 16) | (p[2] << 8) | p[3]; }
uint16_t be16(const uint8_t *p) { return (p[0] << 8) | p[1]; }
String utf8z(const uint8_t *p, size_t n) {
  size_t e = 0; while (e < n && p[e]) e++;
  String s; s.reserve(e);
  for (size_t i = 0; i < e; i++) s += (char)p[i];
  return s;
}

bool decode_variable(const uint8_t *p, size_t n, NavInfo &out) {   // v1
  size_t o = 0;
  if (n < 16) return false;
  out.direction = p[o++];
  out.distance_m = be32(p + o); o += 4;
  uint8_t ln = p[o++]; if (o + ln > n) return false;
  out.nxt = utf8z(p + o, ln); o += ln;
  uint8_t lc = p[o++]; if (o + lc > n) return false;
  out.cur = utf8z(p + o, lc); o += lc;
  uint16_t h = be16(p + o);
  out.remain_s = h * 3600 + p[o + 2] * 60 + p[o + 3];
  out.remain_m = be32(p + o + 4);
  out.speed = be16(p + o + 8);
  out.layout = "variable1";
  return o + 10 <= n;
}

bool decode_variable2(const uint8_t *p, size_t n, NavInfo &out) {  // v2 (CMD 0x40)
  if (n < 21) return false;
  uint32_t image_len = be32(p + 1);
  size_t dist_off;
  if (image_len == 1) {
    if (p[5] > 1) return false;
    dist_off = 6;
  } else if (image_len > 1) {
    if (n < 5 + image_len + 4) return false;
    dist_off = 5 + image_len;      // bo qua JPEG anh mui ten custom
  } else return false;
  out.direction = p[0];
  out.distance_m = be32(p + dist_off);
  size_t o = dist_off + 4;
  uint8_t ln = p[o++]; if (o + ln > n) return false;
  out.nxt = utf8z(p + o, ln); o += ln;
  uint8_t lc = p[o++]; if (o + lc > n) return false;
  out.cur = utf8z(p + o, lc); o += lc;
  uint16_t h = be16(p + o);
  out.remain_s = h * 3600 + p[o + 2] * 60 + p[o + 3];
  out.remain_m = be32(p + o + 4);
  out.speed = be16(p + o + 8);
  out.layout = "variable2";
  return o + 10 <= n;
}

bool decode_fixed(const uint8_t *p, size_t n, NavInfo &out) {      // fixed 0xAF
  if (n < 0xAF) return false;
  out.direction = p[0];
  out.distance_m = be32(p + 1);
  out.nxt = utf8z(p + 5, 0x50);
  out.cur = utf8z(p + 0x55, 0x50);
  uint16_t h = be16(p + 0xA5);
  out.remain_s = h * 3600 + p[0xA7] * 60 + p[0xA8];
  out.remain_m = be32(p + 0xA9);
  out.speed = be16(p + 0xAD);
  out.layout = "fixed";
  return true;
}

void log_nav(const uint8_t *p, size_t n, uint8_t cmd) {
  NavInfo ni; bool ok;
  if (cmd == 0x40) ok = decode_variable2(p, n, ni) || decode_variable(p, n, ni) || decode_fixed(p, n, ni);
  else if (cmd == 0x00) ok = decode_variable(p, n, ni) || decode_fixed(p, n, ni) || decode_variable2(p, n, ni);
  else ok = decode_variable(p, n, ni) || decode_variable2(p, n, ni) || decode_fixed(p, n, ni);
  if (!ok) { Serial.println("[NAV] giai ma that bai - xem hex o tren"); return; }
  Serial.printf("[NAV] %s dir=%d dist=%dm cur=\"%s\" next=\"%s\" remain=%ds/%dm speed=%d\n",
                ni.layout, ni.direction, ni.distance_m,
                ni.cur.c_str(), ni.nxt.c_str(), ni.remain_s, ni.remain_m, ni.speed);
  Serial.println("[NAV] >>> DOI CHIEU: dir byte tren day vs mui ten dang hien thi tren app <<<");
}

// ---------------- xu ly moi khung tron ----------------
void handle_frame(const uint8_t *fr, size_t n) {
  uint32_t lenfield = be32(fr + 4);
  uint8_t cmd = fr[12];
  size_t plen = (size_t)lenfield - 13;
  const uint8_t *pl = fr + 13;
  Serial.printf("[RX ] CMD 0x%02X ts=%u plen=%d : %s\n", cmd,
                (unsigned)be32(fr + 8), (int)plen, hex8(pl, plen).c_str());
  switch (cmd) {
    case 0x0E: {   // getHUDInfo -> tra text MODEL:..,SID:..
      String info = "MODEL:" + g_model + ",HW:" + g_hw + ",FW:" + g_fw +
                    ",PROTOCOL:" + g_protocol + ",OBDV:0_1.0,SID:" + g_sid;
      Serial.println("[EMU] getHUDInfo -> tra: " + info);
      notify_frame(0x0E, (const uint8_t *)info.c_str(), info.length());
      break;
    }
    case 0x02:     // heartbeat (mang toc do)
      Serial.printf("[EMU] heartbeat, speed=%d - khong can tra loi\n", plen >= 1 ? pl[0] : -1);
      break;
    case 0x00:     // dan duong (fixed hoac variable1)
    case 0x40:     // dan duong (variable2 / Simplify)
      log_nav(pl, plen, cmd);
      break;
    default:
      Serial.println("[EMU] khong xu ly CMD nay (van da log hex)");
      break;
  }
}

// quet buffer, tach khung tron (tuong duong vmlhud_frame.split_stream)
void feed_rx(const uint8_t *data, size_t n, const char *which) {
  Serial.printf("[W:%s] %d byte: %s\n", which, (int)n, hex8(data, n).c_str());
  if (g_rxlen + n > sizeof(g_rxbuf)) {
    Serial.println("[EMU] tran buffer - reset");
    g_rxlen = 0;
  }
  memcpy(g_rxbuf + g_rxlen, data, n);
  g_rxlen += n;
  while (g_rxlen >= 29) {   // toi thieu: magic4+len4+ts4+cmd1+md516 = 29
    if (memcmp(g_rxbuf, MAGIC, 4) != 0) {
      // app co the ghi frame qua nhieu chunk, kem byte dan truoc magic
      size_t i = 0;
      while (i + 4 <= g_rxlen && memcmp(g_rxbuf + i, MAGIC, 4) != 0) i++;
      if (i) { memmove(g_rxbuf, g_rxbuf + i, g_rxlen - i); g_rxlen -= i; }
      if (g_rxlen < 29) break;
    }
    uint32_t lenfield = be32(g_rxbuf + 4);
    if (lenfield < 13) { g_rxlen = 0; break; }   // vo ly - reset
    size_t total = 8 + lenfield + MD5_LEN;
    if (total > g_rxlen) break;                   // cho du byte
    // MD5 tren RX khong duoc app dung de gate (chi tinh roi bo) -> khong verify
    handle_frame(g_rxbuf, total);
    memmove(g_rxbuf, g_rxbuf + total, g_rxlen - total);
    g_rxlen -= total;
  }
}

// ---------------- NimBLE callbacks ----------------
struct ServerCB : NimBLEServerCallbacks {
  void onConnect(NimBLEServer *s, NimBLEConnInfo &conn) override {
    g_connected = true;
    Serial.printf("[BLE] da ket noi (VIETMAP LIVE?)\n");
  }
  void onDisconnect(NimBLEServer *s, NimBLEConnInfo &conn, int reason) override {
    g_connected = false;
    g_rxlen = 0;
    Serial.printf("[BLE] ngat ket noi (reason=%d) - quang ba lai\n", reason);
    NimBLEDevice::startAdvertising(0);
  }
};

struct FFF1CB : NimBLECharacteristicCallbacks {
  void onSubscribe(NimBLECharacteristic *c, NimBLEConnInfo &conn, uint16_t sub) override {
    Serial.printf("[BLE] app %s notify FFF1 (sub=0x%04X)\n",
                  sub ? "BAT" : "TAT", sub);
  }
};

struct FFF2CB : NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic *c, NimBLEConnInfo &conn) override {
    std::string v = c->getValue();
    if (v.size()) feed_rx((const uint8_t *)v.data(), v.size(), "FFF2");
  }
};

struct FFF3CB : NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic *c, NimBLEConnInfo &conn) override {
    std::string v = c->getValue();
    if (v.size()) feed_rx((const uint8_t *)v.data(), v.size(), "FFF3");
  }
};

struct H50CB : NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic *c, NimBLEConnInfo &conn) override {
    std::string v = c->getValue();
    if (v.size()) feed_rx((const uint8_t *)v.data(), v.size(), "9ABC");
  }
};

struct H50SUB : NimBLECharacteristicCallbacks {
  void onSubscribe(NimBLECharacteristic *c, NimBLEConnInfo &conn, uint16_t sub) override {
    Serial.printf("[BLE] app %s notify 1234/H50 (sub=0x%04X)\n",
                  sub ? "BAT" : "TAT", sub);
  }
};

// ---------------- scan-request notifier (instance 1, extended) ----------------
struct AdvCB : NimBLEExtAdvertisingCallbacks {
  uint32_t lastMs = 0;
  uint32_t cnt = 0;
  String lastAddr = "";
  void onScanRequest(NimBLEExtAdvertising *pAdv, uint8_t instId, NimBLEAddress addr) override {
    uint32_t now = millis();
    String a = std::string(addr.toString()).c_str();
    cnt++;
    if (now - lastMs > 2000 || a != lastAddr) {
      Serial.printf("[SCAN] %s dang quet board (instance %d, %lu req)\n",
                    a.c_str(), instId, (unsigned long)cnt);
      lastMs = now;
      cnt = 0;
      lastAddr = a;
    }
  }
};

// ---------------- serial console ----------------
void handle_serial() {
  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n');
  line.trim();
  if (!line.length()) return;
  bool known = false;
  auto setv = [&](const String &key, String &dst) {
    if (line.startsWith(key)) {
      dst = line.substring(key.length());
      Serial.println("[CFG] " + key + " = " + dst);
      known = true;
    }
  };
  setv("MODEL:", g_model); setv("HW:", g_hw); setv("FW:", g_fw);
  setv("PROTOCOL:", g_protocol); setv("SID:", g_sid); setv("NAME:", g_name);
  if (line == "STATUS") {
    Serial.printf("[CFG] name=%s model=%s hw=%s fw=%s protocol=%s sid=%s conn=%d\n",
                  g_name.c_str(), g_model.c_str(), g_hw.c_str(), g_fw.c_str(),
                  g_protocol.c_str(), g_sid.c_str(), g_connected);
    known = true;
  } else if (line == "PING") {
    uint8_t demo[16]; memset(demo, 0, sizeof(demo));
    demo[0] = 12; demo[1] = 0; demo[2] = 1; demo[3] = 0x58; demo[4] = 2;  // dist=3458
    log_nav(demo, 16, 0x00);
    known = true;
  }
  if (!known) Serial.println("[CFG] lenh: MODEL:x HW:x FW:x PROTOCOL:x SID:x NAME:x STATUS PING");
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\n[EMU] VIETMAP HUD emulator - mzd-vietnav-hud (NimBLE, ESP32-C3 OK)");
  Serial.println("[EMU] lenh: MODEL:x HW:x FW:x PROTOCOL:x SID:x NAME:x STATUS");

  NimBLEDevice::init(std::string(g_name.c_str()));
  NimBLEServer *srv = NimBLEDevice::createServer();
  srv->setCallbacks(new ServerCB());

  NimBLEService *svc = srv->createService(SVC_H1);
  NimBLECharacteristic *c1 = svc->createCharacteristic(
      CHR_FFF1, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY);
  c1->setCallbacks(new FFF1CB());
  NimBLECharacteristic *c2 = svc->createCharacteristic(
      CHR_FFF2, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::WRITE);
  c2->setCallbacks(new FFF2CB());
  NimBLECharacteristic *c3 = svc->createCharacteristic(
      CHR_FFF3, NIMBLE_PROPERTY::WRITE);
  c3->setCallbacks(new FFF3CB());
  NimBLECharacteristic *c4 = svc->createCharacteristic(
      CHR_FFF4, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY);
  svc->start();

  g_chFFF1 = c1;

  // ---- H50: service FFFF, write 9ABC, notify 1234 ----
  NimBLEService *svcH50 = srv->createService(SVC_H50);
  NimBLECharacteristic *h50w = svcH50->createCharacteristic(
      CHR_9ABC, NIMBLE_PROPERTY::WRITE);
  h50w->setCallbacks(new H50CB());
  NimBLECharacteristic *h50n = svcH50->createCharacteristic(
      CHR_1234, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY);
  h50n->setCallbacks(new H50SUB());
  svcH50->start();
  g_ch1234 = h50n;

  // Quang ba 2 lop qua NimBLEExtAdvertising (can bat CONFIG_BT_NIMBLE_EXT_ADV
  // trong nimconfig.h cua thu vien; ESP32-C3 ho tro):
  //   instance 0: legacy PDUs, connectable - iOS phat hien & ket noi nhu cu
  //   instance 1: extended, scannable, scan-req-notifier - moi app DANG QUET
  //               gay dong [SCAN] tren serial (ky chan ben quet), dung de
  //               chung minh app co thuc su quet hay khong.
  NimBLEExtAdvertising *adv = NimBLEDevice::getAdvertising();
  adv->setCallbacks(new AdvCB());
  {
    NimBLEExtAdvertisement legacy;
    legacy.setLegacyAdvertising(true);
    legacy.setConnectable(true);
    legacy.setScannable(true);
    legacy.addServiceUUID(SVC_H1);
    legacy.addServiceUUID(SVC_H50);
    legacy.setName(std::string(g_name.c_str()));
    if (!adv->setInstanceData(0, legacy)) Serial.println("[ADV] LOI setInstanceData(0)");
    if (!adv->start(0)) Serial.println("[ADV] LOI start(0)");
  }
  {
    NimBLEExtAdvertisement ext;
    ext.setLegacyAdvertising(false);
    ext.setConnectable(false);
    ext.setScannable(true);
    ext.enableScanRequestCallback(true);
    ext.setName(std::string(g_name.c_str()));
    if (!adv->setInstanceData(1, ext)) Serial.println("[ADV] LOI setInstanceData(1)");
    if (!adv->start(1)) Serial.println("[ADV] LOI start(1)");
  }
  Serial.println("[BLE] dang quang ba \"" + g_name + "\" (FFF0+FFFF, scan-req notifier BAT)");
}

void loop() {
  handle_serial();
  delay(20);
}
