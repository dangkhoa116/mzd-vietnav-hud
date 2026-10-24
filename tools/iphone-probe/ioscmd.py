import json, sys, urllib.request
sid = open('iosmcp_session.txt').read().strip()
cmd = sys.argv[1]
req = urllib.request.Request('http://192.168.68.172:8090/mcp',
    data=json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call',
                     'params':{'name':'run_command','arguments':{'command':cmd}}}).encode(),
    headers={'Content-Type':'application/json','mcp-session-id':sid})
r = json.loads(urllib.request.urlopen(req, timeout=60).read())
inner = json.loads(r['result']['content'][0]['text'])
print(inner['output'], end='')
