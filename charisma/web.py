"""Shared HTTP application for the local server and a production WSGI server."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
from http import HTTPStatus
import ipaddress
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import tomllib

from .core import CharismaError
from .guard import GuardStore
from .history import recent_runs, pause_project, undo_candidate
from .monitor import ASSETS, EventStore, valid_origin, validate_event


@dataclass
class Settings:
    database: Path
    origins: list[str]
    site_key: str
    admin_token: str
    read_token: str = ''
    runner_state: Path | None = None
    native_apps: list[str] = field(default_factory=list)
    gateway_token: str = ''
    guard: GuardStore | None = None
    trusted_proxies: list[str] = field(default_factory=list)
    public_origin: str = ''

    def validate(self):
        self.origins=[valid_origin(v) for v in self.origins]
        if self.public_origin: self.public_origin=valid_origin(self.public_origin)
        if not self.origins or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',self.site_key) or len(self.admin_token)<24:
            raise CharismaError('Configure origins, a public site key and a private admin token.')
        private=[v for v in [self.admin_token,self.read_token,self.gateway_token] if v]
        if len(private)!=len(set(private)) or self.site_key in private or any(len(v)<24 for v in private):
            raise CharismaError('Use separate, sufficiently long credentials for every private role.')
        if self.guard and not self.gateway_token: raise CharismaError('Gateway controls require a separate gateway token.')
        if len(self.native_apps)>100 or any(not re.fullmatch(r'[A-Za-z0-9_.-]{3,100}',v) for v in self.native_apps):
            raise CharismaError('Use explicit native application identifiers.')
        self.trusted_proxies=[ipaddress.ip_network(v) for v in self.trusted_proxies]
        if self.database.is_symlink(): raise CharismaError('Database paths cannot be symbolic links.')
        if self.runner_state: self.runner_state=self.runner_state.resolve()


class Application:
    def __init__(self,settings:Settings):
        settings.validate();self.settings=settings
        self.store=EventStore(settings.database)
        with self.store.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS request_limits(key TEXT PRIMARY KEY, start INTEGER, count INTEGER)')
        self.assets={route:((Path(__file__).parent/'static'/file).read_bytes(),kind) for route,(file,kind) in ASSETS.items()}

    def client_ip(self, headers, peer):
        try:
            address=ipaddress.ip_address(peer)
            forwarded=headers.get('x-forwarded-for','')
            if any(address in network for network in self.settings.trusted_proxies) and ',' not in forwarded:
                try:return str(ipaddress.ip_address(forwarded))
                except ValueError:pass
            return str(address)
        except ValueError:return 'unknown'

    def limit(self, namespace, source, maximum=60):
        now=int(time.time());key=hmac.new(self.settings.admin_token.encode(),f'{namespace}:{source}'.encode(),hashlib.sha256).hexdigest()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM request_limits WHERE start<?',(now-120,))
            row=db.execute('SELECT start,count FROM request_limits WHERE key=?',(key,)).fetchone()
            start,count=row if row and now-row[0]<60 else (now,0)
            # Bound a botnet's ability to fill this table.
            if not row and db.execute('SELECT COUNT(*) FROM request_limits').fetchone()[0]>=10000:return False
            db.execute('INSERT OR REPLACE INTO request_limits VALUES(?,?,?)',(key,start,count+1))
        return count < maximum

    def authenticate(self, headers, role='read'):
        supplied=headers.get('authorization','').encode()
        candidates=[self.settings.admin_token]
        if role=='read' and self.settings.read_token:candidates.append(self.settings.read_token)
        if role=='gateway':candidates=[self.settings.gateway_token] if self.settings.gateway_token else []
        return any(hmac.compare_digest(supplied,('Bearer '+token).encode()) for token in candidates)

    def handle(self, method, path, headers, body=b'',peer='127.0.0.1'):
        headers={k.lower():v for k,v in headers.items()};origin=headers.get('origin','');source=self.client_ip(headers,peer)
        response_headers={'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY',
            'Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"}
        def reply(code,value,kind=None):
            data=value if isinstance(value,bytes) else json.dumps(value).encode()
            if kind:response_headers['Content-Type']=kind
            return code,response_headers,data
        def payload():
            if headers.get('content-type','').split(';')[0].strip()!='application/json' or not body or len(body)>4096:
                raise CharismaError('Send a JSON payload of at most 4096 bytes.')
            value=json.loads(body)
            if not isinstance(value,dict):raise CharismaError('Expected a JSON object.')
            return value
        try:
            if len(body)>4096:return reply(413,{'error':'Payload exceeds the limit.'})
            if method=='GET' and path in self.assets:
                data,kind=self.assets[path];return reply(200,data,kind)
            if method=='GET' and path=='/health':return reply(200,{'status':'ok'})
            if method=='GET' and path=='/ready':
                with self.store.connect() as db:db.execute('SELECT 1 FROM events LIMIT 1')
                return reply(200,{'status':'ready'})
            if path=='/ingest' and origin in self.settings.origins:
                response_headers.update({'Access-Control-Allow-Origin':origin,'Vary':'Origin','Access-Control-Allow-Headers':'Content-Type, X-Charisma-Site-Key','Access-Control-Allow-Methods':'POST, OPTIONS'})
            if method=='OPTIONS':
                return reply(200 if path=='/ingest' and origin in self.settings.origins else 403,{})
            if path in {'/ingest','/ingest/native'} and method=='POST':
                if not self.limit('ingest',source):return reply(429,{'error':'Report limit reached.'})
                native=path=='/ingest/native'
                allowed=headers.get('x-charisma-app-id') in self.settings.native_apps if native else origin in self.settings.origins
                if not allowed or not hmac.compare_digest(headers.get('x-charisma-site-key','').encode(),self.settings.site_key.encode()):
                    return reply(403,{'error':'This installation is not enabled.'})
                event=validate_event(payload())
                if native and event['code'] not in {'ios-error','android-error'}:raise CharismaError('Unsupported native event.')
                if not native and event['code'] in {'ios-error','android-error'}:raise CharismaError('Use the native event endpoint.')
                self.store.record(event);return reply(202,{'accepted':True})
            if path in {'/edge/check','/edge/signal'}:
                if not self.authenticate(headers,'gateway'):return reply(401,{'error':'Gateway authentication required.'})
                if not self.settings.guard:return reply(503,{'error':'Gateway policy is unavailable.'})
                if path=='/edge/check' and method=='GET':
                    decision=self.settings.guard.decision(headers.get('x-charisma-service',''),headers.get('x-charisma-source-ip',''))
                    if not decision['allowed']:response_headers['Retry-After']=str(decision['retry_after'])
                    return reply(204 if decision['allowed'] else 403,b'' if decision['allowed'] else {'error':'Request denied by service policy.'})
                if path=='/edge/signal' and method=='POST':
                    if not self.limit('gateway_signals',source,2000):return reply(429,{'error':'Gateway signal limit reached.'})
                    return reply(202,self.settings.guard.signal(payload()))
                return reply(405,{'error':'Method not allowed.'})
            if path.startswith('/api/'):
                if not self.limit('admin',source,120):return reply(429,{'error':'Dashboard request limit reached.'})
                role='read' if method=='GET' else 'operator'
                if not self.authenticate(headers,role):return reply(401,{'error':'The access token was not accepted for this operation.'})
                if method!='GET' and origin and self.settings.public_origin and origin!=self.settings.public_origin:
                    return reply(403,{'error':'Cross-origin control request rejected.'})
                if method=='GET' and path=='/api/events':return reply(200,{'events':self.store.list(),'updated_at':int(time.time()),'limit':200,'can_control':self.authenticate(headers,'operator')})
                if method=='GET' and path=='/api/runs':return reply(200,recent_runs(self.settings.runner_state))
                if method=='GET' and path=='/api/security':
                    return reply(200,{'enabled':bool(self.settings.guard),**(self.settings.guard.snapshot() if self.settings.guard else {})})
                if method=='POST' and path=='/api/security/control':
                    if not self.settings.guard:return reply(409,{'error':'Gateway policy is not configured.'})
                    return reply(200,self.settings.guard.control(payload()))
                match=re.fullmatch(r'/api/events/([0-9]{1,12})/review',path)
                if method=='POST' and match:
                    ok=self.store.review(int(match.group(1)));return reply(200 if ok else 404,{'reviewed':ok})
                action=re.fullmatch(r'/api/runs/([0-9a-f]{16})/(pause|resume|undo)',path)
                if method=='POST' and action:
                    if self.settings.runner_state is None:return reply(409,{'error':'Worker history is not connected.'})
                    run_id,operation=action.groups()
                    result=undo_candidate(self.settings.runner_state,run_id) if operation=='undo' else pause_project(self.settings.runner_state,run_id,operation=='pause')
                    return reply(200,result)
            return reply(404,{'error':'Not found.'})
        except CharismaError as exc:return reply(400,{'error':str(exc)})
        except (ValueError,TypeError,KeyError):return reply(400,{'error':'Invalid request fields or values.'})
        except (sqlite3.Error,OSError):return reply(503,{'error':'The service is temporarily unavailable.'})

    def __call__(self,environ,start_response):
        method=environ.get('REQUEST_METHOD','GET');path=environ.get('PATH_INFO','/')
        headers={name[5:].replace('_','-').lower():value for name,value in environ.items() if name.startswith('HTTP_')}
        if environ.get('CONTENT_TYPE'):headers['content-type']=environ['CONTENT_TYPE']
        try:
            length=int(environ.get('CONTENT_LENGTH') or 0)
            if length<0 or length>4096 or headers.get('transfer-encoding'):raise ValueError()
            body=environ['wsgi.input'].read(length) if length else b''
            if len(body)!=length:raise ValueError()
            code,response_headers,data=self.handle(method,path,headers,body,environ.get('REMOTE_ADDR','unknown'))
        except ValueError:
            code,response_headers,data=400,{'Content-Type':'application/json','Cache-Control':'no-store'},b'{"error":"Invalid request framing or size."}'
        response_headers['Content-Length']=str(len(data))
        start_response(f'{code} {HTTPStatus(code).phrase}',list(response_headers.items()))
        return [data]


def secret(name):
    file=os.environ.get(name+'_FILE')
    if file:
        path=Path(file)
        if path.stat().st_size>4096:raise CharismaError('Secret file exceeds the size limit.')
        return path.read_text().strip()
    return os.environ.get(name,'')


def create_app():
    """Production entry point. Invalid or incomplete configuration stops startup."""
    os.umask(0o077)
    config_path=os.environ.get('CHARISMA_SERVER_CONFIG','/etc/charisma/server.toml')
    with Path(config_path).open('rb') as stream:config=tomllib.load(stream)
    public=config.get('public_origin','')
    if not public.startswith('https://'):raise CharismaError('Production requires an HTTPS public_origin.')
    admin=secret('CHARISMA_ADMIN_TOKEN');gateway=secret('CHARISMA_GATEWAY_TOKEN');audit_key=secret('CHARISMA_AUDIT_KEY');reader=secret('CHARISMA_READ_TOKEN')
    if len(set([v for v in (admin,gateway,audit_key,reader) if v]))!=len([v for v in (admin,gateway,audit_key,reader) if v]):
        raise CharismaError('Use different operator, reader, gateway and audit secrets.')
    guard=GuardStore(Path(config.get('security_database','/data/security.sqlite3')),config['services'],audit_key) if config.get('services') else None
    return Application(Settings(database=Path(config.get('database','/data/events.sqlite3')),origins=config['origins'],site_key=config['site_key'],admin_token=admin,read_token=reader,gateway_token=gateway,guard=guard,public_origin=public,
        native_apps=config.get('native_apps',[]),trusted_proxies=config.get('trusted_proxies',[]),runner_state=Path(config['runner_state']) if config.get('runner_state') else None))
