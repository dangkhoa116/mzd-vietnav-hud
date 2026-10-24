// v3 PASSIVE-ABSOLUTE: onEnter chi dung JS thuan (khong ObjC.* call, khong readPointer).
function log(m){ console.log(m); }
function hook(cls, sel) {
  const c = ObjC.classes[cls]; if (!c) return;
  let m = null; try { m = c['- ' + sel]; } catch(e){}
  if (!m) return;
  try { Interceptor.attach(m.implementation, {
    onEnter(a){ log('[' + cls + '] ' + sel + ' a2=' + a[2]); }
  }); } catch(e){}
}
['setInstructionVariants:','setSymbolImage:','setSymbolSet:','setManeuverType:','setJunctionType:','setInitialTravelEstimates:','setDashboardInstructionVariants:','setUserInfo:','setAttributedInstructionVariants:'].forEach(s => hook('CPManeuver', s));
hook('CPMapTemplate', 'startNavigationSessionForTrip:');
hook('CPNavigationSession', 'setUpcomingManeuvers:');
hook('CPNavigationSession', 'updateTravelEstimates:forManeuver:');
hook('CPNavigationSession', 'cancelTrip');
for (const n of ['VIETMAPCarPlayManager2','VIETMAPCarPlayDashboardManager2']) {
  const c = ObjC.classes[n]; if (!c) continue;
  const wanted = [];
  try { const arr = c.$methods;
    for (let i = 0; i < arr.length; i++) { try { const nm = String(arr[i].selector || ''); if (/startedTrip|didConnectInterfaceController/.test(nm)) wanted.push(nm); } catch(e){} }
  } catch(e){}
  for (const sel of wanted) { let m = null; try { m = c['- ' + sel]; } catch(e){}
    if (m) { try { Interceptor.attach(m.implementation, { onEnter(){ log('[' + n + '] ' + sel); } }); } catch(e){} } }
}
// DJBT: chi log ten method
const dcls = ObjC.classes['DJBTManager'];
if (dcls) for (const sel of ['- sendNavigationInformationWithDirection:andDistance:andNextRoad:andCurrentRoad:andRemainTime:andRemainDistance:andCurrentSpeed:','- sendCustomNavigationInformationWithDirection:andDirectionImage:andDistance:andNextRoad:andCurrentRoad:andRemainTime:andRemainDistance:andCurrentSpeed:','- sendEndNavigationInformation','- sendHeartBeat']) {
  let m = null; try { m = dcls[sel]; } catch(e){}
  if (m) { try { Interceptor.attach(m.implementation, { onEnter(){ log('[DJBT] ' + sel.slice(2,50)); } }); } catch(e){} }
}
log('=== v3 passive armed ===');
