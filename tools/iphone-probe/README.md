# Bộ tool probe iPhone jailbreak (VIETMAP LIVE + CarPlay)

Sinh ra từ các phiên probe 23–25/10/2026 (docs/iphone-probe-results.vi.md).
Mọi script chạy từ PC, điện thoại jailbreak (Dopamine rootless) cần:
ios-mcp (tweak substrate, HTTP :8090) + frida-server port 27043.

## Thành phần

| File | Chức năng |
|---|---|
| `vm_hook_runner.py` | Runner frida: attach theo PID, splice ObjC bridge, shim console.log→send (frida 17 không đẩy console về Python). `python vm_hook_runner.py <pid> <script.js> <out.log>` |
| `vm_supervisor.py` | Giữ hooks luôn dính theo app: tự gắn lại khi VietMap bị kill/relaunch. `python vm_supervisor.py <script.js> <out.log>` |
| `vm_cp_v3.js` | Hook THỤ ĐỘNG CarPlay maneuver (CPManeuver/CPNavigationSession/CPMapTemplate + DJBT BLE): chỉ log tên selector. |
| `vm_strings.js` | Đọc giá trị chuỗi `setInstructionVariants:` / `setUpcomingManeuvers:` (tên đường nguyên bản UTF-8). |
| `vm_drive6.js` | XE ẢO GPS: hook delegate `VMLocationEngine.LocationEngine`, thay mảng CLLocation (args[3]) bằng vị trí giả đi về đích 28 m/lần. Sửa `DEST` trong file. |
| `vm_deleg_hunt.js` | Tìm delegate location của app (hook mọi class implement `locationManager:didUpdateLocations:`). |
| `ioscmd.py` | JSON-RPC client tối giản cho ios-mcp `run_command`. |
| `q3_strings_final.txt` | Bộ 88 chuỗi instructionVariants nguyên văn thu được 25-10 (xe ảo 48 km). |

## Quy tắc sống còn (2 lần crash app đã trả giá)

**KHÔNG gọi bất kỳ API ObjC nào trên tham số tùy tiện trong onEnter/onLeave.**

1. `describe()`/`ObjC.Object()` trên giá trị số (direction 0xFF=255) →
   `object_getClass` segfault.
2. `class_getName(isa)` → chết trong `objc_class::demangledName` (Swift
   class chưa demangle trên isa lạ).

Hook an toàn = chỉ log tên selector + con trỏ thô (vm_cp_v3.js), hoặc
hook HẸP có kiểu biết trước và chỉ đọc object chính app truyền vào
(vm_strings.js — chạy ổn >30 phút). Muốn chuỗi hiển thị: ghép screenshot
banner với thời điểm hook, hoặc dùng vm_strings.js.

Ghi chú ABI arm64 đã trả giá: struct 2 double (CLLocationCoordinate2D)
là HFA → trả về thanh ghi SIMD v0/v1 (frida không expose); selector
2 tham số: args[2]=tham số 1, args[3]=tham số 2. `coordinate()` qua
bridge trả mảng `[lat, lon]`.
