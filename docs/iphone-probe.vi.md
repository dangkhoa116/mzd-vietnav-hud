# Nhiệm vụ trên iPhone jailbreak: VietMap đưa gì sang CarPlay?

Tài liệu cho một agent/kỹ thuật viên làm việc trên **iPhone đã jailbreak chạy
được VIETMAP LIVE**. Bạn không cần biết gì về phần xe; mọi thứ cần đều ở đây.

Đọc hết mục 1–3 trước khi gõ lệnh. Mục 3 là thứ **đã biết rồi, đừng làm lại**.

---

## 1. Bối cảnh ngắn

Trên xe Mazda (CMU150) có một cầu nối đưa dẫn đường CarPlay lên **HUD zin**
(kính lái). Đã kiểm trên xe thật:

- **Google Maps qua CarPlay → HUD hiện mũi tên bình thường.**
- **VIETMAP LIVE qua CarPlay → HUD trống hoàn toàn.**

Cầu nối đọc khung iAP2 `0x8059` mà **iPhone phát ra** cho xe, lấy trường
`maneuverType` ở offset `0x128`, rồi phân loại. Giá trị `0` nghĩa là *NoTurn*
và bị coi là "mục ngữ cảnh", nên bị **vứt bỏ hoàn toàn**.

Giả thuyết đang theo: **VietMap không bao giờ đặt `CPManeuver.maneuverType`**,
nên mọi maneuver của nó tới xe với giá trị 0 và bị lọc sạch. Đã viết bản vá cho
phía xe: khi `maneuverType == 0` thì **suy hướng rẽ từ chuỗi chữ**
(`maneuverDesc`, offset `0x24` của cùng khung).

**Việc của bạn: xác nhận hoặc bác bỏ giả thuyết đó từ phía điện thoại, và lấy
về chuỗi chữ thật.** Phía xe không trả lời được câu này nếu iPhone vốn không
phát gì.

---

## 2. Câu hỏi cần trả lời, theo thứ tự ưu tiên

| # | Câu hỏi | Vì sao quan trọng |
| --- | --- | --- |
| **Q1** | Khi VietMap dẫn đường, nó gọi **những setter nào** của `CPManeuver`, với giá trị gì? | Trả lời thẳng giả thuyết |
| **Q2** | `setManeuverType:` có **bao giờ** được gọi không (kể cả gián tiếp qua KVC)? | Nếu CÓ thì giả thuyết sai, phải tìm hướng khác |
| **Q3** | Chuỗi đưa vào `setInstructionVariants:` **nguyên văn** là gì? | Bộ nhận dạng chữ phía xe phải khớp đúng cách hành văn này |
| **Q4** | Có `CPNavigationSession` thật sự được tạo không? `setUpcomingManeuvers:` có được gọi liên tục khi đang chạy không? | Phân biệt "app không khai dẫn đường" với "app khai nhưng thiếu trường" |

Q3 là thứ **giá trị nhất mà bạn lấy được kể cả khi không có đầu CarPlay** (xem
mục 4.1). Q1/Q2/Q4 cần một phiên CarPlay thật.

---

## 3. Đã biết sẵn — đừng mất thời gian làm lại

Phân tích tĩnh IPA `vn.vietmap.live` **3.4.3** (đã làm xong):

### 3.1 App có khai dẫn đường CarPlay đầy đủ

- `CFBundleIdentifier`: `vn.vietmap.live`, bản `3.4.3`, `MinimumOSVersion` 15.0
- Entitlement **`com.apple.developer.carplay-maps`** (bắt buộc với app dẫn
  đường CarPlay)
- `Info.plist` khai cả hai scene:

| Role | Scene | Delegate |
| --- | --- | --- |
| `CPTemplateApplicationSceneSessionRoleApplication` | CarPlay | `vietmap_live_navigation_plugin.VIETMAPCarPlayManager2` |
| `CPTemplateApplicationDashboardSceneSessionRoleApplication` | CarPlay-Dashboard | `vietmap_live_navigation_plugin.VIETMAPCarPlayDashboardManager2` |

### 3.2 Selector nào có, selector nào không

Quét toàn bộ Mach-O trong bundle:

| Selector | Có trong binary nào |
| --- | --- |
| `startNavigationSessionForTrip:` | `vietmap_live_navigation_plugin` |
| `setUpcomingManeuvers:` | `vietmap_live_navigation_plugin` |
| `updateTravelEstimates:forManeuver:` | `vietmap_live_navigation_plugin` |
| `setInstructionVariants:` | `vietmap_live_navigation_plugin` |
| `setSymbolImage:` | `vietmap_live_navigation_plugin` |
| **`setManeuverType:`** | **không có ở đâu cả** |
| `setJunctionType:` | không có |
| `junctionExitAngle` | không có |
| `setAttributedInstructionVariants:` | không có |
| `setDashboardInstructionVariants:` | không có |

**Chi tiết đáng chú ý:** chuỗi `maneuverType` *có* xuất hiện trong
`App.framework/App` và trong `vml_live_activities` / `VMLiveActivities` — tức
app **có** khái niệm "kiểu rẽ" nội bộ (dùng cho Live Activities / Dynamic
Island), nó chỉ **không chuyển sang CarPlay**. Dữ liệu tồn tại; chỗ đứt nằm ở
cầu nối CarPlay.

### 3.3 Plugin viết bằng Swift

`vietmap_live_navigation_plugin` là Swift (tên mangled kiểu `CPManeuverCSg…`).
Nghĩa là **không swizzle được hàm nội bộ của nó theo kiểu ObjC**. Nhưng
`CPManeuver`, `CPNavigationSession`, `CPMapTemplate` là lớp **ObjC** của
`CarPlay.framework`, nên **setter của chúng móc được bình thường** — đó là chỗ
nên móc, vì nó bắt mọi thứ app đặt bất kể ngôn ngữ.

### 3.4 Từ vựng rẽ đã đọc được từ app

Chuỗi tiếng Việt của app nằm trong Dart AOT snapshot
(`Payload/Runner.app/Frameworks/App.framework/App`) và lưu **UTF-16LE**
(`TwoByteString` của Dart — quét UTF-8 sẽ **không ra gì**, đừng mất thời gian).
Từ vựng rẽ tìm được:

```
Rẽ phải / Rẽ trái
Rẽ gấp sang phải / Rẽ gấp sang trái
Rẽ hơi lệch sang phải / Rẽ hơi lệch sang trái
Tiếp tục đi thẳng
Vào bùng binh và đi theo lối ra thứ …
```

**Nhưng đây mới là từ vựng app đóng gói sẵn.** Chưa biết chuỗi thực sự đưa vào
`setInstructionVariants:` có phải mấy câu này không, hay do API dẫn đường sinh
lúc chạy. **Q3 chính là để trả lời chỗ đó.**

---

## 4. Cách làm

Ba bài, xếp từ rẻ đến đắt. Làm được bài nào gửi kết quả bài đó, không cần đủ cả ba.

### 4.1 Bài A — Lấy chuỗi dẫn đường (KHÔNG cần đầu CarPlay)

Đây là bài nên làm trước: chỉ cần dẫn đường bình thường trên điện thoại.

**Cách 1: bắt phản hồi API tuyến đường.** Chuỗi lệnh gần như chắc chắn đến từ
`bannerInstructions` / `voiceInstructions` trong phản hồi tuyến. Máy jailbreak
thì cài CA của mitmproxy rồi chạy proxy là xong. Lưu lại **nguyên JSON một
tuyến có nhiều kiểu rẽ**.

**Cách 2: móc cầu Flutter.** Plugin là một `FlutterPlugin`, nên phương thức
`handleMethodCall:result:` là **selector ObjC**, móc được:

```js
// frida -U -n "VIETMAP LIVE" -l hook.js
for (const name of Object.keys(ObjC.classes)) {   // ObjC.classes la object, khong iterate bang `of`
  if (!/VIETMAP|Vietmap|Navigation/.test(name)) continue;
  const cls = ObjC.classes[name];
  const sel = '- handleMethodCall:result:';
  if (!cls[sel]) continue;
  console.log('[+] hook', name);
  Interceptor.attach(cls[sel].implementation, {
    onEnter(args) {
      const call = new ObjC.Object(args[2]);
      console.log('[channel]', call.method(), '=>', String(call.arguments()));
    }
  });
}
```

### 4.2 Bài B — Móc thẳng `CPManeuver` (CẦN phiên CarPlay)

Phải có kết nối CarPlay thật thì scene mới chạy: một đầu CarPlay rời, hoặc
dongle CarPlay, hoặc xe có CarPlay. Không có thì bỏ qua bài này, báo lại là
không thực hiện được.

```js
// Liet ke MOI setter cua CPManeuver thuc su duoc goi, kem gia tri.
const CPManeuver = ObjC.classes.CPManeuver;
const want = [
  'setInstructionVariants:', 'setSymbolImage:', 'setSymbolSet:',
  'setManeuverType:', 'setJunctionType:', 'setJunctionExitAngle:',
  'setJunctionElementAngles:', 'setInitialTravelEstimates:',
  'setHighwayExitLabel:', 'setNotificationTitle:', 'setUserInfo:',
  'setAttributedInstructionVariants:', 'setDashboardInstructionVariants:',
];
for (const sel of want) {
  const m = CPManeuver['- ' + sel];
  if (!m) { console.log('[-] khong co:', sel); continue; }
  Interceptor.attach(m.implementation, {
    onEnter(args) {
      let v = '(?)';
      try { v = String(new ObjC.Object(args[2])); }
      catch (e) { v = 'scalar=' + args[2].toInt32(); }
      console.log('[CPManeuver]', sel, v);
    }
  });
  console.log('[+] da hook', sel);
}

// KVC: Swift co the dat thuoc tinh qua setValue:forKey: thay vi setter.
// Hook nay rat "nong" (ca app di qua day) nen chi bat khi can, va da loc bang regex.
Interceptor.attach(ObjC.classes.NSObject['- setValue:forKey:'].implementation, {
  onEnter(args) {
    const key = String(new ObjC.Object(args[3]));
    if (/maneuver|junction|instruction/i.test(key)) {
      console.log('[KVC]', String(new ObjC.Object(args[0]).$className),
                  key, '=', String(new ObjC.Object(args[2])));
    }
  }
});
```

Và phía phiên dẫn đường:

```js
const log = (cls, sel) => {
  const c = ObjC.classes[cls]; if (!c || !c['- ' + sel]) return;
  Interceptor.attach(c['- ' + sel].implementation, {
    onEnter(a) { console.log('[' + cls + ']', sel, String(new ObjC.Object(a[2]))); }
  });
};
log('CPMapTemplate', 'startNavigationSessionForTrip:');
log('CPNavigationSession', 'setUpcomingManeuvers:');
log('CPNavigationSession', 'updateTravelEstimates:forManeuver:');
log('CPNavigationSession', 'cancelTrip');
```

### 4.3 Bài C — Nếu không có đầu CarPlay nào

Dùng `vietmap_hud_sdk.framework`: app nói chuyện BLE với thiết bị HUD VietMap,
và luồng đó **có** mang mã hướng rẽ + tên đường. Nhưng phía chúng tôi đã giải
mã xong luồng này rồi, nên bài này **giá trị thấp** — chỉ làm nếu A và B đều
không làm được.

---

## 5. Cạm bẫy

- **Phiên bản iOS quyết định ý nghĩa kết quả.** `CPManeuver.maneuverType` chỉ
  có **từ iOS 17.4**. Nếu máy jailbreak của bạn là iOS 16.x thì setter đó
  *không tồn tại trên hệ điều hành*, và việc nó không được gọi **không chứng
  minh được gì** về app. **Bắt buộc báo lại model máy + phiên bản iOS.** Máy
  dùng để test trên xe là iPhone Air / iOS 27.0.1.
- **Plugin là Swift**, đừng cố hook hàm nội bộ của nó bằng tên ObjC. Hook lớp
  `CP*` của hệ thống.
- **Quét chuỗi tiếng Việt phải dùng UTF-16LE**, không phải UTF-8 (mục 3.4).
- Scene CarPlay **không chạy** nếu không có kết nối CarPlay; mọi hook `CPManeuver`
  sẽ im lặng, và đó **không** phải bằng chứng app không đặt gì.
- Frida 17.24.3 đã chạy tốt với máy jailbreak trong dự án này.

---

## 6. Cần gửi về những gì

1. **Model máy + phiên bản iOS** (bắt buộc, nếu thiếu thì mọi kết luận vô giá trị).
2. Có kết nối CarPlay được không; nếu có thì bằng thiết bị gì.
3. **Danh sách setter `CPManeuver` thực sự được gọi**, kèm giá trị. Nói rõ
   `setManeuverType:` có được gọi không, kể cả qua KVC.
4. **10–20 chuỗi lệnh nguyên văn**, cố gắng phủ đủ các loại:
   rẽ thường, rẽ gấp, rẽ chếch, đi thẳng, quay đầu, vòng xuyến, nhập làn,
   giữ làn, lối ra cao tốc, đã đến đích.
   Giữ **nguyên dấu tiếng Việt**, đừng sửa lại cho gọn — bộ nhận dạng khớp theo
   từng từ, sửa một chữ là hỏng.
5. Nếu bắt được: **một phản hồi API tuyến đường** dạng JSON có nhiều kiểu rẽ.
6. Nếu `setInstructionVariants:` được gọi với **mảng nhiều chuỗi**: ghi rõ thứ
   tự và đầy đủ các phần tử (CarPlay chọn chuỗi theo chiều rộng màn hình, nên
   xe có thể nhận phần tử khác phần tử đầu).

Kết quả của mục 3 và 4 quyết định hướng đi tiếp của cả nhánh CarPlay.
