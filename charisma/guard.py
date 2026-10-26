"""Scoped defensive controls. Only authenticated gateway signals can create auto-blocks."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import sqlite3
import time

from .core import CharismaError

SERVICE = re.compile(r'[a-z][a-z0-9_-]{0,39}')


class GuardStore:
    def __init__(self, path: Path, services: dict, audit_key: str):
        if not audit_key or len(audit_key) < 32:
            raise CharismaError('Configure a separate audit key with at least 32 characters.')
        if not services or len(services) > 100:
            raise CharismaError('Configure between one and 100 explicit service identifiers.')
        self.path, self.services, self.key = path, services, audit_key.encode()
        for name, policy in services.items():
            if not SERVICE.fullmatch(name) or not isinstance(policy, dict):
                raise CharismaError('Invalid service policy.')
            if type(policy.get('auto_block', False)) is not bool:
                raise CharismaError('auto_block must be true or false.')
            for field, default, low, high in [('threshold',20,5,1000),('window_seconds',60,10,3600),('block_seconds',600,30,3600)]:
                value=policy.get(field,default)
                if type(value) is not int or not low <= value <= high:
                    raise CharismaError('A gateway policy exceeds its permitted bounds.')
            policy['protected_networks']=[ipaddress.ip_network(n) for n in policy.get('protected_networks',['127.0.0.0/8','::1/128'])]
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink(): raise CharismaError('The security database cannot be a symbolic link.')
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS blocks(service TEXT, ip TEXT, expires INTEGER, reason TEXT, PRIMARY KEY(service,ip));
                CREATE TABLE IF NOT EXISTS quarantine(service TEXT PRIMARY KEY, expires INTEGER, reason TEXT);
                CREATE TABLE IF NOT EXISTS signals(id TEXT PRIMARY KEY, service TEXT, ip TEXT, kind TEXT, received INTEGER);
                CREATE INDEX IF NOT EXISTS signal_window ON signals(service,ip,received);
                CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER, payload TEXT, previous TEXT, signature TEXT);
            ''')
            db.execute('PRAGMA journal_mode=WAL')
        os.chmod(path,0o600)

    def connect(self):
        connection=sqlite3.connect(self.path,timeout=5)
        connection.execute('PRAGMA busy_timeout=5000')
        return connection

    def service(self, service):
        if service not in self.services: raise CharismaError('This service is not registered.')
        return self.services[service]

    def ip(self, value):
        try: return str(ipaddress.ip_address(value))
        except ValueError: raise CharismaError('Supply one valid source IP address.') from None

    def protected(self, policy, source):
        address=ipaddress.ip_address(source)
        return any(address in network for network in policy['protected_networks'])

    def audit(self, db, event):
        last=db.execute('SELECT signature FROM audit ORDER BY seq DESC LIMIT 1').fetchone()
        previous=last[0] if last else '0'*64
        at=int(time.time())
        payload=json.dumps(event,sort_keys=True,separators=(',',':'))
        signature=hmac.new(self.key,f'{at}\n{previous}\n{payload}'.encode(),hashlib.sha256).hexdigest()
        db.execute('INSERT INTO audit(at,payload,previous,signature) VALUES(?,?,?,?)',(at,payload,previous,signature))

    def signal(self, event):
        if not isinstance(event,dict) or set(event) != {'id','service','source_ip','kind'}:
            raise CharismaError('Invalid gateway signal schema.')
        if not isinstance(event['id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',event['id']):
            raise CharismaError('Signals require a stable unique identifier.')
        policy=self.service(event['service']); source=self.ip(event['source_ip'])
        if event['kind'] not in {'auth_failure','rate_limit','server_error'}:
            raise CharismaError('Unsupported server signal.')
        now=int(time.time()); service=event['service']
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM signals WHERE received < ?',(now-86400,))
            if db.execute('SELECT COUNT(*) FROM signals').fetchone()[0] >= 100000:
                raise CharismaError('The signal buffer is full. Inspect the gateway before accepting more signals.')
            inserted=db.execute('INSERT OR IGNORE INTO signals VALUES(?,?,?,?,?)',(event['id'],service,source,event['kind'],now)).rowcount
            count=db.execute("SELECT COUNT(*) FROM signals WHERE service=? AND ip=? AND received>=? AND kind='auth_failure'",(service,source,now-policy.get('window_seconds',60))).fetchone()[0]
            blocked=False
            if inserted and event['kind']=='auth_failure' and policy.get('auto_block',False) and count >= policy.get('threshold',20) and not self.protected(policy,source):
                expiry=now+policy.get('block_seconds',600)
                existing=db.execute('SELECT expires FROM blocks WHERE service=? AND ip=?',(service,source)).fetchone()
                if not existing or existing[0] <= now:
                    db.execute('INSERT OR REPLACE INTO blocks VALUES(?,?,?,?)',(service,source,expiry,'Repeated authenticated gateway reports of failed access'))
                    self.audit(db,{'actor':'gateway_policy','action':'temporary_block','service':service,'source_ip':source,'expires':expiry,'signals':count})
                blocked=True
            return {'accepted':bool(inserted),'duplicate':not bool(inserted),'auto_blocked':blocked,'service':service}

    def decision(self, service, source):
        self.service(service); source=self.ip(source); now=int(time.time())
        with self.connect() as db:
            quarantine=db.execute('SELECT expires FROM quarantine WHERE service=? AND expires>?',(service,now)).fetchone()
            if quarantine: return {'allowed':False,'reason':'service_isolated','retry_after':quarantine[0]-now}
            block=db.execute('SELECT expires FROM blocks WHERE service=? AND ip=? AND expires>?',(service,source,now)).fetchone()
            if block: return {'allowed':False,'reason':'temporary_block','retry_after':block[0]-now}
        return {'allowed':True,'reason':'policy_allows'}

    def control(self, event):
        if not isinstance(event,dict) or set(event) != {'action','service','source_ip','seconds','reason'}:
            raise CharismaError('Invalid control schema.')
        policy=self.service(event['service']); action=event['action']; now=int(time.time())
        if action not in {'block','unblock','isolate','resume'}: raise CharismaError('Unsupported control action.')
        if type(event['seconds']) is not int or not 30 <= event['seconds'] <= 3600:
            raise CharismaError('Defensive leases must be between 30 and 3600 seconds.')
        reason=event['reason']
        if not isinstance(reason,str) or not 3 <= len(reason) <= 200 or any(ord(c)<32 for c in reason):
            raise CharismaError('Give a short reason without private customer data.')
        source=self.ip(event['source_ip']) if action in {'block','unblock'} else ''
        if action=='block' and self.protected(policy,source): raise CharismaError('This address is in the protected operator network list.')
        service=event['service']; expires=now+event['seconds']
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if action=='block': db.execute('INSERT OR REPLACE INTO blocks VALUES(?,?,?,?)',(service,source,expires,reason))
            elif action=='unblock': db.execute('DELETE FROM blocks WHERE service=? AND ip=?',(service,source))
            elif action=='isolate': db.execute('INSERT OR REPLACE INTO quarantine VALUES(?,?,?)',(service,expires,reason))
            else: db.execute('DELETE FROM quarantine WHERE service=?',(service,))
            self.audit(db,{'actor':'operator','action':action,'service':service,'source_ip':source,'expires':expires if action in {'block','isolate'} else None,'reason':reason})
        return {'action':action,'service':service,'expires':expires if action in {'block','isolate'} else None}

    def snapshot(self):
        now=int(time.time())
        with self.connect() as db:
            db.row_factory=sqlite3.Row
            blocks=[dict(r) for r in db.execute('SELECT * FROM blocks WHERE expires>? ORDER BY expires DESC LIMIT 200',(now,))]
            isolated=[dict(r) for r in db.execute('SELECT * FROM quarantine WHERE expires>?',(now,))]
            audit=[{**dict(r),'event':json.loads(r['payload'])} for r in db.execute('SELECT * FROM audit ORDER BY seq DESC LIMIT 100')]
        return {'services':[{ 'id':name,'auto_block':policy.get('auto_block',False)} for name,policy in self.services.items()], 'blocks':blocks,'isolated':isolated,'audit':audit}

    def verify_audit(self):
        previous='0'*64;count=0
        with self.connect() as db:
            for at,payload,parent,signature in db.execute('SELECT at,payload,previous,signature FROM audit ORDER BY seq'):
                expected=hmac.new(self.key,f'{at}\n{previous}\n{payload}'.encode(),hashlib.sha256).hexdigest()
                if parent != previous or not hmac.compare_digest(signature,expected):
                    return {'valid':False,'records_checked':count}
                count+=1;previous=signature
        return {'valid':True,'records_checked':count,'head':previous}
