// Tim + hook tat ca class implement locationManager:didUpdateLocations:
const SEL = '- locationManager:didUpdateLocations:';
const names = Object.keys(ObjC.classes).filter(n => /loc|stream|engine|geo/i.test(n) && n.length < 60);
console.log('scan ' + names.length + ' classes...');
let armed = 0;
for (const n of names) {
  let c; try { c = ObjC.classes[n]; } catch (e) { continue; }
  let m = null; try { m = c[SEL]; } catch (e) {}
  if (!m) continue;
  try {
    Interceptor.attach(m.implementation, {
      onEnter(args) {
        this.arr = args[2];
        console.log('[HIT] ' + n);
      }
    });
    armed++;
    console.log('armed ' + n);
  } catch (e) {}
}
console.log('hunt armed on ' + armed + ' classes');
