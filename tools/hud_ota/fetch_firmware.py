"""Fetch HUD firmware using an operator-provided session; never prints/saves token."""
import argparse, getpass, hashlib, json, urllib.request, urllib.error
from pathlib import Path

API='https://api.vietmap.live/production/v20/hud/updatefirmware'
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('request',type=Path,help='Six-field request JSON from the selected HUD')
    p.add_argument('--out',type=Path,default=Path('out/hud-firmware-download'))
    args=p.parse_args()
    body=json.loads(args.request.read_text(encoding='utf-8-sig'))
    fields={'model','hardwareVersion','firmwareVersion','obdModel','obdVersion','serialNumber'}
    if set(body)!=fields or any(not isinstance(v,str) or '<' in v for v in body.values()):
        p.error('Supply exactly the six observed fields, with explicit string values.')
    token=getpass.getpass('Session bearer token (hidden; not saved): ').strip()
    if token.lower().startswith('bearer '): token=token[7:]
    if not token or any(c in token for c in '\r\n'): p.error('Invalid token input')
    req=urllib.request.Request(API,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Accept':'application/json','Authorization':'Bearer '+token},method='POST')
    opener=urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(req,timeout=30) as r: raw=r.read(2*1024*1024+1)
    except urllib.error.HTTPError as e:
        print('Metadata request HTTP',e.code,'; no credential logged.'); return 1
    if len(raw)>2*1024*1024: raise RuntimeError('Metadata exceeds limit')
    result=json.loads(raw)
    args.out.mkdir(parents=True,exist_ok=False)
    (args.out/'metadata.json').write_bytes(raw)
    candidates=[]
    def walk(x):
        if isinstance(x,dict):
            if isinstance(x.get('downloadUrl'),str) and x['downloadUrl']: candidates.append(x)
            for v in x.values(): walk(v)
        elif isinstance(x,list):
            for v in x: walk(v)
    walk(result)
    if len(candidates)!=1:
        print('Saved metadata; downloadUrl count:',len(candidates),'; inspect locally.'); return 2
    selected=candidates[0]; url=selected['downloadUrl']
    if not url.startswith('https://'): raise RuntimeError('Expected explicit HTTPS firmware URL')
    # Separate opener and request: account Authorization is never sent to the file host.
    target=args.out/'firmware.partial'
    h=hashlib.sha256(); total=0
    with urllib.request.urlopen(urllib.request.Request(url,headers={'Accept':'application/octet-stream'}),timeout=60) as r, target.open('xb') as f:
        if 'text/html' in r.headers.get('content-type','').lower(): raise RuntimeError('File response is HTML')
        while True:
            chunk=r.read(128*1024)
            if not chunk: break
            total+=len(chunk)
            if total>128*1024*1024: raise RuntimeError('Firmware exceeds 128 MiB limit')
            h.update(chunk); f.write(chunk)
    target.rename(args.out/'firmware.download')
    target=args.out/'firmware.download'
    (args.out/'SHA256.txt').write_text(h.hexdigest()+'  firmware.download\n')
    print('Downloaded',total,'bytes to',target,'SHA256',h.hexdigest())
    return 0
if __name__=='__main__': raise SystemExit(main())
