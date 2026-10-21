// SPDX-License-Identifier: AGPL-3.0-or-later
// Experimental BLE HUD peer for owned-device interoperability, not Mazda HUD output.
// Arduino ESP32 3.3.2 + NimBLE-Arduino 2.3.7; ESP32C3 Dev Module, USB CDC enabled.
#include <NimBLEDevice.h>
#include <Preferences.h>
#include <atomic>
#include <mutex>
#include "mbedtls/md5.h"
#include "hud_codec.h"

String g_name="VMHUD-EMU", g_model="H50", g_hw="1.0.0", g_fw="1.0.0";
String g_protocol="2.2.2S", g_sid="VMEMU0000001";
Preferences g_store;
std::mutex g_cfgMutex;
std::atomic<bool> g_connected{false};
uint16_t g_conn=BLE_HS_CONN_HANDLE_NONE;
NimBLECharacteristic *g_h1=nullptr, *g_h50=nullptr;
bool g_subH1=false, g_subH50=false;
vmhud::Receiver<4096> g_rxH1, g_rxH50;

bool sdkChecksum(const uint8_t *p, size_t n, const uint8_t *uid, uint8_t *out) {
  uint8_t digest[16];
  mbedtls_md5_context ctx;
  mbedtls_md5_init(&ctx);
  int rc=mbedtls_md5_starts(&ctx);
  if (!rc) rc=mbedtls_md5_update(&ctx,p,n);
  if (!rc) rc=mbedtls_md5_update(&ctx,uid,16);
  if (!rc) rc=mbedtls_md5_finish(&ctx,digest);
  mbedtls_md5_free(&ctx);
  if (rc) return false;
  vmhud::put32(out,vmhud::be32(digest)+vmhud::be32(digest+4)+vmhud::be32(digest+8)+vmhud::be32(digest+12));
  return true;
}
String text(const uint8_t *p, size_t n) {
  String value;value.reserve(n);
  for (size_t i=0;i<n && p[i];i++) value+=(char)p[i];
  return value;
}
void printHex(const uint8_t *p, size_t n) {
  // Preserve one hex line per BLE write for host capture decoding.
  for (size_t i=0;i<n;i++) Serial.printf("%02X",p[i]);
  Serial.println();
}
void notifyInfo(const vmhud::Frame &request, NimBLECharacteristic *route) {
  const bool subscribed=route==g_h1?g_subH1:g_subH50;
  if (!g_connected || !subscribed) { Serial.println("[EMU] HUDInfo requested before notify subscription");return; }
  String info;
  {
    std::lock_guard<std::mutex> guard(g_cfgMutex);
    info="MODEL:"+g_model+",HW:"+g_hw+",FW:"+g_fw+",PROTOCOL:"+g_protocol+",OBDV:0_1.0,SID:"+g_sid;
  }
  static uint8_t frame[512];
  const size_t count=vmhud::build(0x0e,(const uint8_t *)info.c_str(),info.length(),request.timestamp,
                                frame,sizeof(frame),sdkChecksum,request.legacy);
  if (!count) { Serial.println("[EMU] HUDInfo exceeds TX capacity or checksum failed");return; }
  // ATT MTU is at least 23. Never rely on notify() fragmenting a whole frame.
  for (size_t offset=0;offset<count;offset+=20) {
    const size_t chunk=count-offset<20?count-offset:20;
    if (!route->notify(frame+offset,chunk,g_conn)) { Serial.println("[EMU] notify queue failed; wait for app retry");return; }
  }
  Serial.printf("[EMU] HUDInfo via %s, %u bytes: %s\n",route==g_h1?"FFF1":"1234",(unsigned)count,info.c_str());
}
void onFrame(const vmhud::Frame &frame, void *user) {
  Serial.printf("[RX ] %s CMD 0x%02X ts=%u plen=%u : ",frame.legacy?"legacy":"new",frame.command,
                (unsigned)frame.timestamp,(unsigned)frame.size);
  printHex(frame.payload,frame.size);
  if (frame.command==0x0e) { notifyInfo(frame,(NimBLECharacteristic *)user);return; }
  if (frame.command==0 || frame.command==0x40) {
    vmhud::Nav nav;
    if (!vmhud::navigation(frame,nav)) { Serial.println("[NAV] rejected malformed/unsupported payload; keep RX hex");return; }
    const String current=text(nav.current,nav.currentSize),next=text(nav.next,nav.nextSize);
    Serial.printf("[NAV] %s dir=%u dist=%um cur=\"%s\" next=\"%s\" remaining=%uh/%um/third_raw=%u remain_m=%u speed_raw=%u\n",
                  nav.layout,nav.direction,(unsigned)nav.distance,current.c_str(),next.c_str(),nav.hours,
                  nav.minutes,nav.timeThird,(unsigned)nav.remainingDistance,nav.speed);
    // Variable-format third time byte is not assumed to be seconds in the iOS SDK.
  } else if (frame.command==1 && frame.size==4) {
    Serial.printf("[CAM] type_raw=%u dist=%um limit_raw=%u\n",frame.payload[0],vmhud::be16(frame.payload+1),frame.payload[3]);
  } else if (frame.command==2 && (frame.size==1 || frame.size==2)) {
    Serial.printf("[HB ] speed_raw=%u\n",frame.size==1?frame.payload[0]:vmhud::be16(frame.payload));
  }
}
void startConnectable() {
  const bool ok=NimBLEDevice::startAdvertising(0);
  Serial.printf("[ADV] connectable start %s\n",ok?"OK":"FAILED");
}
struct ServerCB : NimBLEServerCallbacks {
  void onConnect(NimBLEServer *server, NimBLEConnInfo &conn) override {
    if (g_connected) { server->disconnect(conn.getConnHandle());return; }
    g_conn=conn.getConnHandle();g_connected=true;g_subH1=g_subH50=false;
    g_rxH1.reset();g_rxH50.reset();Serial.println("[BLE] connected; wait for notify subscription + HUDInfo request");
  }
  void onDisconnect(NimBLEServer *, NimBLEConnInfo &conn, int reason) override {
    if (conn.getConnHandle()!=g_conn) return;
    g_connected=false;g_conn=BLE_HS_CONN_HANDLE_NONE;g_subH1=g_subH50=false;
    g_rxH1.reset();g_rxH50.reset();Serial.printf("[BLE] disconnected reason=%d\n",reason);startConnectable();
  }
};
struct SubscribeCB : NimBLECharacteristicCallbacks {
  void onSubscribe(NimBLECharacteristic *c, NimBLEConnInfo &conn, uint16_t sub) override {
    if (conn.getConnHandle()!=g_conn) return;
    if (c==g_h1) g_subH1=(sub&1)!=0;else g_subH50=(sub&1)!=0;
    Serial.printf("[BLE] notify %s sub=0x%04X\n",c==g_h1?"FFF1":"1234",sub);
  }
};
struct WriteCB : NimBLECharacteristicCallbacks {
  NimBLECharacteristic *route;const char *label;vmhud::Receiver<4096> *rx;
  WriteCB(NimBLECharacteristic *r,const char *l,vmhud::Receiver<4096> *b):route(r),label(l),rx(b) {}
  void onWrite(NimBLECharacteristic *c,NimBLEConnInfo &conn) override {
    if (conn.getConnHandle()!=g_conn) return;
    const std::string data=c->getValue();
    Serial.printf("[W:%s] %u byte: ",label,(unsigned)data.size());
    printHex((const uint8_t *)data.data(),data.size());
    const size_t before=rx->dropped;
    rx->feed((const uint8_t *)data.data(),data.size(),sdkChecksum,onFrame,route);
    if (rx->dropped!=before) Serial.printf("[EMU] rejected corrupt/oversize frames: %u\n",(unsigned)(rx->dropped-before));
  }
};
#if CONFIG_BT_NIMBLE_EXT_ADV
#if CONFIG_BT_NIMBLE_MAX_EXT_ADV_INSTANCES < 2
#error "Extended scan diagnostic needs CONFIG_BT_NIMBLE_MAX_EXT_ADV_INSTANCES=2"
#endif
struct AdvCB : NimBLEExtAdvertisingCallbacks {
  uint32_t last=0,count=0;
  void onScanRequest(NimBLEExtAdvertising *,uint8_t instance,NimBLEAddress) override {
    count++;
    if (millis()-last>2000) {
      Serial.printf("[SCAN] instance=%u requests=%u; scanner/app identity unknown\n",instance,(unsigned)count);
      last=millis();count=0;
    }
  }
};
#endif
void setupAdvertising() {
  auto *adv=NimBLEDevice::getAdvertising();
#if CONFIG_BT_NIMBLE_EXT_ADV
  adv->setCallbacks(new AdvCB());
  NimBLEExtAdvertisement primary;
  primary.setLegacyAdvertising(true);primary.setConnectable(true);primary.setScannable(true);
  primary.setFlags(0x06);primary.addServiceUUID("FFF0");primary.addServiceUUID("FFFF");
  primary.setName(std::string(g_name.c_str()));
  if (!adv->setInstanceData(0,primary)) Serial.println("[ADV] primary configuration FAILED");
  startConnectable();
  NimBLEExtAdvertisement diagnostic;
  diagnostic.setLegacyAdvertising(false);diagnostic.setConnectable(false);diagnostic.setScannable(true);
  diagnostic.enableScanRequestCallback(true);diagnostic.setName(std::string(g_name.c_str()));
  if (!adv->setInstanceData(1,diagnostic) || !adv->start(1)) Serial.println("[ADV] optional scan diagnostic FAILED");
  Serial.println("[ADV] optional extended scan diagnostic enabled; absence of SCAN proves nothing about VietMap");
#else
  NimBLEAdvertisementData primary;
  primary.setFlags(0x06);primary.addServiceUUID("FFF0");primary.addServiceUUID("FFFF");
  primary.setName(std::string(g_name.c_str()));
  adv->enableScanResponse(false);
  if (!adv->setAdvertisementData(primary)) Serial.println("[ADV] primary configuration FAILED");
  startConnectable();
#endif
  Serial.println("[BLE] name and FFF0+FFFF are in primary advertisement: "+g_name);
}
void handleSerial() {
  static String line;
  static bool overflow=false;
  while (Serial.available()) {
    const char ch=(char)Serial.read();
    if (ch=='\r') continue;
    if (ch!='\n') {
      if (!overflow && line.length()<160) line+=ch;
      else { overflow=true;line=""; }
      continue;
    }
    if (overflow) { overflow=false;line="";Serial.println("[CFG] line too long; ignored");continue; }
    line.trim();
    if (line=="STATUS") {
      std::lock_guard<std::mutex> guard(g_cfgMutex);
      Serial.printf("[CFG] name=%s model=%s hw=%s fw=%s protocol=%s sid=%s connected=%d\n",
                    g_name.c_str(),g_model.c_str(),g_hw.c_str(),g_fw.c_str(),g_protocol.c_str(),g_sid.c_str(),g_connected.load());
    } else if (line=="PING") {
      const uint8_t known[]={0xa5,0x5a,0x37,0xc3,0,0,0,0x0e,0,0,0,0,0x0e,0,0x4d,0xc6,0x42,0x15,0xc1,0xc4,0x8d,0xa3};
      vmhud::Frame parsed;
      Serial.printf("[PING] frozen SDK-format vector: %s\n",vmhud::parse(known,sizeof(known),sdkChecksum,parsed)?"OK":"FAIL");
    } else {
      const int split=line.indexOf(':');
      const String key=split<0?"":line.substring(0,split),value=split<0?"":line.substring(split+1);
      String *target=nullptr;const char *storeKey=nullptr;
      if (key=="MODEL") { target=&g_model;storeKey="model"; }
      if (key=="HW") { target=&g_hw;storeKey="hw"; }
      if (key=="FW") { target=&g_fw;storeKey="fw"; }
      if (key=="PROTOCOL") { target=&g_protocol;storeKey="protocol"; }
      if (key=="SID") { target=&g_sid;storeKey="sid"; }
      if (key=="NAME") { target=&g_name;storeKey="name"; }
      bool valid=target && value.length()>0 && value.length()<=64 && value.indexOf(',')<0 && value.indexOf(':')<0;
      if (key=="NAME") valid=valid && value.length()<=20 && value.indexOf("HUD")>=0 && value.indexOf("TPMS")<0;
      if (valid) {
        { std::lock_guard<std::mutex> guard(g_cfgMutex);*target=value; }
        if (!g_store.putString(storeKey,value)) Serial.println("[CFG] NVS write FAILED");
        else Serial.println("[CFG] saved "+key+(key=="NAME"?"; reset board to apply name":""));
      } else Serial.println("[CFG] STATUS / PING / MODEL:x / HW:x / FW:x / PROTOCOL:x / SID:x / NAME:x");
    }
    line="";
  }
}
void setup() {
  Serial.begin(115200);delay(200);
  Serial.println("\n[EMU] VIETMAP HUD BLE trial, ESP32-C3; no Mazda HUD output yet");
  if (g_store.begin("vmhud",false)) {
    g_name=g_store.getString("name",g_name);g_model=g_store.getString("model",g_model);
    g_hw=g_store.getString("hw",g_hw);g_fw=g_store.getString("fw",g_fw);
    g_protocol=g_store.getString("protocol",g_protocol);g_sid=g_store.getString("sid",g_sid);
  }
  NimBLEDevice::init(std::string(g_name.c_str()));
  NimBLEServer *server=NimBLEDevice::createServer();server->setCallbacks(new ServerCB());
  NimBLEService *h1=server->createService("FFF0");
  g_h1=h1->createCharacteristic("FFF1",NIMBLE_PROPERTY::READ|NIMBLE_PROPERTY::NOTIFY);
  g_h1->setCallbacks(new SubscribeCB());
  const uint32_t writable=NIMBLE_PROPERTY::WRITE|NIMBLE_PROPERTY::WRITE_NR;
  h1->createCharacteristic("FFF2",writable)->setCallbacks(new WriteCB(g_h1,"FFF2",&g_rxH1));
  h1->createCharacteristic("FFF3",writable)->setCallbacks(new WriteCB(g_h1,"FFF3",&g_rxH1));
  h1->createCharacteristic("FFF4",NIMBLE_PROPERTY::READ|NIMBLE_PROPERTY::NOTIFY);
  h1->start();
  NimBLEService *h50=server->createService("FFFF");
  g_h50=h50->createCharacteristic("1234",NIMBLE_PROPERTY::READ|NIMBLE_PROPERTY::NOTIFY);
  g_h50->setCallbacks(new SubscribeCB());
  h50->createCharacteristic("9ABC",writable)->setCallbacks(new WriteCB(g_h50,"9ABC",&g_rxH50));
  h50->start();setupAdvertising();
  Serial.println("[EMU] Serial 115200: STATUS, PING, MODEL:x, PROTOCOL:x, SID:x, NAME:x");
}
void loop() { handleSerial();delay(10); }
