"""Tests only the disposable localhost containers launched by CI."""
import json
import os
from pathlib import Path
import time
import urllib.request
import urllib.error

ADMIN=Path(os.environ['FIXTURE_ADMIN_FILE']).read_text().strip() if os.environ.get('FIXTURE_ADMIN_FILE') else 'integration-admin-token-32-characters'
GATEWAY=Path(os.environ['FIXTURE_GATEWAY_FILE']).read_text().strip() if os.environ.get('FIXTURE_GATEWAY_FILE') else 'integration-gateway-token-32-characters'

def request(port,path='/',data=None,token=None,headers=None):
    headers=headers or {}
    if token:headers['Authorization']='Bearer '+token
    if data is not None:headers['Content-Type']='application/json'
    base={18787:os.environ.get('FIXTURE_MONITOR','http://127.0.0.1:18787'),18080:os.environ.get('FIXTURE_WEBSITE','http://127.0.0.1:18080'),18081:os.environ.get('FIXTURE_ACCOUNTS','http://127.0.0.1:18081')}[port]
    req=urllib.request.Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=5) as response:return response.status,response.read()
    except urllib.error.HTTPError as error:return error.code,error.read()

assert request(18787,'/ready')[0]==200
assert request(18080)[0]==200 and request(18081)[0]==200
control={'action':'isolate','service':'website','source_ip':'','seconds':60,'reason':'Disposable integration test'}
assert request(18787,'/api/security/control',control,ADMIN)[0]==200
assert request(18080)[0]==403
assert request(18081)[0]==200
assert request(18787,'/api/security/control',{**control,'action':'resume'},ADMIN)[0]==200
assert request(18080)[0]==200
for i in range(5):
    status,_=request(18787,'/edge/signal',{'id':f'integration-signal-{i}','service':'website','source_ip':'192.0.2.50','kind':'auth_failure'},GATEWAY)
    assert status==202
headers={'X-Charisma-Service':'website','X-Charisma-Source-IP':'192.0.2.50'}
assert request(18787,'/edge/check',token=GATEWAY,headers=headers)[0]==403
assert request(18787,'/edge/check',token=GATEWAY,headers={**headers,'X-Charisma-Service':'accounts'})[0]==204
# A browser's public installation key cannot trigger gateway controls.
assert request(18787,'/edge/signal',{'id':'not-authorised'},headers={'X-Charisma-Site-Key':'public-integration-key'})[0]==401
print('Gateway quarantine, recovery, service isolation and trusted-signal blocking passed.')
