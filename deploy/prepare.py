"""Generate local deployment secrets without printing them. Run on your own server."""
from pathlib import Path
import os
import secrets

root=Path(__file__).resolve().parent
for folder in ['secrets','state','caddy-data','caddy-config']:
    path=root/folder;path.mkdir(exist_ok=True);path.chmod(0o700)
for name in ['admin_token','read_token','gateway_token','audit_key']:
    path=root/'secrets'/name
    if not path.exists():
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:f.write(secrets.token_urlsafe(48)+'\n')
print('Private deployment files are ready. No credentials were printed.')
print('On Linux, assign deploy/secrets, state, caddy-data and caddy-config to container UID 10001 before launch.')
