// Xe ao v6: thay mang location trong delegate THAT cua VietMap
// (VMLocationEngine.LocationEngine.locationManager:didUpdateLocations:).
const DEST = { lat: 10.77259, lon: 106.70528 };
const STEP_M = 28;
let fake = null, n = 0;
const cls = ObjC.classes['VMLocationEngine.LocationEngine'];
const m = cls['- locationManager:didUpdateLocations:'];
Interceptor.attach(m.implementation, {
  onEnter(args) {
    n++;
    try {
      if (!fake) {
        // doc vi tri that lam goc (object that tu he thong — an toan)
        const arr = new ObjC.Object(args[3]);
        const loc = arr.objectAtIndex_(0);
        const c = loc.coordinate();
        fake = { lat: c[0], lon: c[1] };
        console.log('[d6] SEED ' + fake.lat.toFixed(6) + ',' + fake.lon.toFixed(6));
      }
      // di chuyen
      const latM = 111320.0, lonM = 111320.0 * Math.cos(fake.lat * Math.PI / 180);
      const dy = (DEST.lat - fake.lat) * latM, dx = (DEST.lon - fake.lon) * lonM;
      const d = Math.sqrt(dy * dy + dx * dx);
      if (d > 1e-6) { const k = STEP_M / d; fake.lat += dy * k / latM; fake.lon += dx * k / lonM; }
      // tao CLLocation + NSArray moi
      const newLoc = ObjC.classes.CLLocation.alloc().initWithLatitude_longitude_(fake.lat, fake.lon);
      args[3] = ObjC.classes.NSArray.arrayWithObject_(newLoc);
      if (n % 3 === 0) console.log('[d6] GPS ' + fake.lat.toFixed(6) + ',' + fake.lon.toFixed(6) + ' con ' + (d / 1000).toFixed(2) + 'km n=' + n);
    } catch (e) { if (n < 30) console.log('[d6] err ' + e.message); }
  }
});
console.log('[d6] armed on VMLocationEngine.LocationEngine');
