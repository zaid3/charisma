import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from charisma.core import CharismaError
from charisma.guard import GuardStore
from charisma.web import Application, Settings

ADMIN='test-admin-credential-with-32-characters'
GATEWAY='test-gateway-credential-with-32-characters'
READER='test-read-credential-with-32-characters'
AUDIT='test-independent-audit-secret-32-characters'


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store=GuardStore(self.root/'guard.db',{'shop':{'auto_block':True,'threshold':5},'accounts':{'auto_block':False}},AUDIT)
        self.app=Application(Settings(self.root/'events.db',['https://shop.example'],'public-site-key',ADMIN,read_token=READER,gateway_token=GATEWAY,guard=self.store,public_origin='https://monitor.example',native_apps=['io.example.app']))

    def signal(self,n,service='shop',kind='auth_failure',ip='192.0.2.10'):
        return {'id':f'fixture-event-{n}','service':service,'source_ip':ip,'kind':kind}

    def test_repeated_trusted_failures_create_expiring_service_scoped_block(self):
        with patch('charisma.guard.time.time',return_value=1000):
            for i in range(5): self.store.signal(self.signal(i))
            self.assertFalse(self.store.decision('shop','192.0.2.10')['allowed'])
            self.assertTrue(self.store.decision('accounts','192.0.2.10')['allowed'])
        with patch('charisma.guard.time.time',return_value=1700):
            self.assertTrue(self.store.decision('shop','192.0.2.10')['allowed'])
        self.assertTrue(self.store.verify_audit()['valid'])

    def test_duplicate_events_and_server_errors_cannot_trigger_block(self):
        for _ in range(10): self.store.signal(self.signal(1))
        for i in range(10): self.store.signal(self.signal(i+2,kind='server_error'))
        self.assertTrue(self.store.decision('shop','192.0.2.10')['allowed'])
        for i in range(10): self.store.signal(self.signal(i+20,ip='127.0.0.1'))
        self.assertTrue(self.store.decision('shop','127.0.0.1')['allowed'])

    def test_service_isolation_and_recovery_are_bounded_and_audited(self):
        event={'action':'isolate','service':'shop','source_ip':'','seconds':60,'reason':'Investigating fixture'}
        self.store.control(event)
        self.assertFalse(self.store.decision('shop','192.0.2.20')['allowed'])
        self.assertTrue(self.store.decision('accounts','192.0.2.20')['allowed'])
        self.store.control({**event,'action':'resume'})
        self.assertTrue(self.store.decision('shop','192.0.2.20')['allowed'])
        with self.store.connect() as db:db.execute("UPDATE audit SET payload='modified' WHERE seq=1")
        self.assertFalse(self.store.verify_audit()['valid'])

    def test_read_token_cannot_mutate_and_browser_cannot_act_as_gateway(self):
        headers={'Authorization':'Bearer '+READER,'Content-Type':'application/json'}
        event={'action':'isolate','service':'shop','source_ip':'','seconds':60,'reason':'Fixture'}
        self.assertEqual(self.app.handle('POST','/api/security/control',headers,json.dumps(event).encode())[0],401)
        self.assertEqual(self.app.handle('GET','/api/security',headers)[0],200)
        self.assertEqual(self.app.handle('POST','/edge/signal',headers,json.dumps(self.signal(1)).encode())[0],401)
        headers['Authorization']='Bearer '+ADMIN;headers['Origin']='https://other.example'
        self.assertEqual(self.app.handle('POST','/api/security/control',headers,json.dumps(event).encode())[0],403)

    def test_gateway_missing_policy_and_spoofed_forwarding_fail_closed(self):
        headers={'Authorization':'Bearer '+GATEWAY,'X-Charisma-Service':'unknown','X-Charisma-Source-IP':'192.0.2.1'}
        self.assertEqual(self.app.handle('GET','/edge/check',headers)[0],400)
        self.assertEqual(self.app.client_ip({'x-forwarded-for':'203.0.113.10'},'192.0.2.3'),'192.0.2.3')
        trusted=Application(Settings(self.root/'trusted.db',['https://shop.example'],'public-site-key',ADMIN,trusted_proxies=['192.0.2.0/24']))
        self.assertEqual(trusted.client_ip({'x-forwarded-for':'203.0.113.10'},'192.0.2.3'),'203.0.113.10')
        self.assertEqual(trusted.client_ip({'x-forwarded-for':'203.0.113.10, 198.51.100.1'},'192.0.2.3'),'192.0.2.3')

    def test_native_events_require_registered_application_and_bounded_schema(self):
        event={'code':'ios-error','error':'Unknown','file':'','line':0,'column':0,'count':1,'page':'checkout'}
        headers={'X-Charisma-Site-Key':'public-site-key','X-Charisma-App-ID':'io.example.app','Content-Type':'application/json'}
        self.assertEqual(self.app.handle('POST','/ingest/native',headers,json.dumps(event).encode())[0],202)
        self.assertEqual(self.app.handle('POST','/ingest/native',{**headers,'X-Charisma-App-ID':'unknown'},json.dumps(event).encode())[0],403)
        self.assertEqual(self.app.handle('POST','/ingest/native',headers,json.dumps({**event,'message':'private'}).encode())[0],400)

    def test_wsgi_framing_health_and_security_headers(self):
        status=[]
        data=self.app({'REQUEST_METHOD':'GET','PATH_INFO':'/ready','REMOTE_ADDR':'127.0.0.1','wsgi.input':io.BytesIO()},lambda s,h:status.append((s,dict(h))))
        self.assertEqual(status[0][0],'200 OK');self.assertIn('Content-Security-Policy',status[0][1])
        status=[]
        self.app({'REQUEST_METHOD':'POST','PATH_INFO':'/ingest','CONTENT_LENGTH':'999999','wsgi.input':io.BytesIO()},lambda s,h:status.append(s))
        self.assertEqual(status[0],'400 Bad Request')

    def test_rate_limit_shared_between_wsgi_workers(self):
        other=Application(Settings(self.root/'events.db',['https://shop.example'],'public-site-key',ADMIN))
        for _ in range(3):self.assertTrue(self.app.limit('shared','192.0.2.2',3))
        self.assertFalse(other.limit('shared','192.0.2.2',3))
