// Doc chuoi nguyen van tu CarPlay maneuver stream. Hook hep, chi typed args.
function nsarr(p) {
  try {
    if (!p || p.isNull() || p.compare('0x10000') < 0) return null;
    const a = new ObjC.Object(p);          // NSArray that app truyen vao
    const cn = a.$className;
    if (cn.indexOf('Array') === -1) return '(' + cn + ')';
    const n = a.count();
    const parts = [];
    for (let i = 0; i < Math.min(n, 4); i++) {
      const s = a.objectAtIndex_(i);
      parts.push(String(s));
    }
    return parts.join(' || ');
  } catch (e) { return '(err ' + e.message + ')'; }
}
const M = ObjC.classes.CPManeuver;
for (const sel of ['setInstructionVariants:', 'setDashboardInstructionVariants:', 'setAttributedInstructionVariants:']) {
  let m = null; try { m = M['- ' + sel]; } catch(e){}
  if (!m) continue;
  Interceptor.attach(m.implementation, {
    onEnter(args) { console.log('[STR] ' + sel + ' => ' + nsarr(args[2])); }
  });
}
let m2 = null; try { m2 = ObjC.classes.CPNavigationSession['- setUpcomingManeuvers:']; } catch(e){}
if (m2) Interceptor.attach(m2.implementation, {
  onEnter(args) {
    try {
      const a = new ObjC.Object(args[2]);
      const n = a.count();
      const parts = [];
      for (let i = 0; i < Math.min(n, 5); i++) {
        const man = a.objectAtIndex_(i);
        // instructionVariants cua tung maneuver
        let instr = '?';
        try { const iv = man.instructionVariants(); instr = String(iv.objectAtIndex_(0)); } catch(e){}
        parts.push(instr);
      }
      console.log('[SESSION] setUpcomingManeuvers n=' + n + ' => ' + parts.join(' || '));
    } catch (e) { console.log('[SESSION] err ' + e.message); }
  }
});
console.log('=== strings hooks armed ===');
